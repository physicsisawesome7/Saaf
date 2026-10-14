"""Saaf gateway: an OpenAI- and Anthropic-compatible proxy that masks PII on
the way out and restores it on the way back, including streamed responses.

Point an SDK at the gateway instead of the provider::

    OpenAI(base_url="http://localhost:8787/v1")
    Anthropic(base_url="http://localhost:8787")

Each request gets its own :class:`saaf.Saaf` session, so tokens never leak
across requests or tenants. The vault lives only for the request.
"""

from __future__ import annotations

import inspect
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from saaf import AuditLogger, Detector, JsonlSink, MaskResult, Policy, Saaf, __version__
from saaf_gateway.config import GatewayConfig
from saaf_gateway.sse import restore_anthropic_stream, restore_openai_stream

OPENAI_FORWARD = ("authorization", "openai-organization", "openai-project", "openai-beta")
ANTHROPIC_FORWARD = ("x-api-key", "authorization", "anthropic-version", "anthropic-beta")


class Gateway:
    def __init__(self, config: GatewayConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.client = httpx.AsyncClient(timeout=config.timeout, transport=transport)
        self.audit = (
            AuditLogger(JsonlSink(config.audit_log), config.audit_key)
            if config.audit_log and config.audit_key
            else None
        )
        self._policies: dict[str, Policy] = {}

    def policy_for(self, tenant: str) -> Policy:
        if tenant in self._policies:
            return self._policies[tenant]
        policy = Policy()
        if self.config.policy_dir and GatewayConfig.valid_tenant(tenant):
            path = self.config.policy_dir / f"{tenant}.toml"
            if path.is_file():
                policy = Policy.load(path)
            elif self.config.default_policy:
                policy = Policy.load(self.config.default_policy)
        elif self.config.default_policy:
            policy = Policy.load(self.config.default_policy)
        self._policies[tenant] = policy
        return policy

    def session(self, request: Request) -> tuple[Saaf, str]:
        tenant = request.headers.get(self.config.tenant_header, "default")
        if not GatewayConfig.valid_tenant(tenant):
            raise HTTPException(400, f"invalid tenant name in {self.config.tenant_header}")
        policy = self.policy_for(tenant)
        return Saaf(policy, detector=_detector(policy.enabled_entities)), tenant


@lru_cache(maxsize=32)
def _detector(entities: tuple[str, ...] | None) -> Detector:
    return Detector(entities=entities)


def _summary_header(results: list[MaskResult]) -> str:
    counts: Counter[str] = Counter()
    for r in results:
        counts.update(r.entity_counts)
    return ",".join(f"{k}={v}" for k, v in sorted(counts.items()))


def _blocked_response(results: list[MaskResult]) -> JSONResponse:
    entities = sorted({a.finding.entity for r in results for a in r.applied if a.action == "block"})
    return JSONResponse(
        {"error": {"type": "saaf_blocked", "message": "request blocked by data policy", "entities": entities}},
        status_code=403,
    )


def _forward_headers(request: Request, names: tuple[str, ...]) -> dict[str, str]:
    return {n: v for n in names if (v := request.headers.get(n)) is not None}


def _record(gw: Gateway, saaf: Saaf, tenant: str, results: list[MaskResult], destination: str, endpoint: str) -> None:
    if gw.audit is None:
        return
    gw.audit.record(
        "proxy",
        tenant=tenant,
        entities=[a.finding.entity for r in results for a in r.applied],
        actions=[a.action for r in results for a in r.applied],
        mode=saaf.policy.mode,
        policy=saaf.policy.fingerprint,
        destination=destination,
        blocked=any(r.blocked for r in results),
        extra={"endpoint": endpoint},
    )


async def _lines(resp: httpx.Response) -> AsyncIterator[str]:
    async for line in resp.aiter_lines():
        yield line


def create_app(config: GatewayConfig | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    gw = Gateway(config or GatewayConfig.from_env(), transport)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await gw.client.aclose()

    app = FastAPI(title="Saaf gateway", version=__version__, lifespan=lifespan)
    app.state.gateway = gw
    if gw.config.cors_origins:
        # Lets a browser page (e.g. safearly.com/playground) call a gateway on
        # localhost. Off unless SAAF_CORS_ORIGINS names the origins.
        cors: dict[str, Any] = {
            "allow_origins": list(gw.config.cors_origins),
            "allow_methods": ["GET", "POST"],
            "allow_headers": ["authorization", "content-type", "x-api-key", "anthropic-version", "x-saaf-tenant"],
            "expose_headers": ["x-saaf-entities", "x-saaf-mode"],
            "max_age": 600,
        }
        if "allow_private_network" in inspect.signature(CORSMiddleware.__init__).parameters:
            cors["allow_private_network"] = True  # Chrome: public page -> localhost preflight
        app.add_middleware(CORSMiddleware, **cors)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/v1/saaf/entities")
    async def entities() -> list[dict[str, Any]]:
        return [
            {"id": e.id, "label": e.label, "phase": e.phase, "severity": e.severity} for e in _detector(None).entities
        ]

    @app.post("/v1/saaf/scan")
    async def scan(request: Request) -> dict[str, Any]:
        """Detection only. Returns types, offsets and scores, never values."""
        body = await request.json()
        saaf, _tenant = gw.session(request)
        findings = saaf.scan(str(body.get("text", "")))
        return {"findings": [f.to_dict() for f in findings]}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        body = await request.json()
        saaf, tenant = gw.session(request)
        upstream = gw.config.upstream_openai
        dest = urlparse(upstream).hostname or upstream
        messages, results = saaf.mask_messages(body.get("messages") or [], destination=dest)
        _record(gw, saaf, tenant, results, dest, "chat.completions")
        if any(r.blocked for r in results):
            return _blocked_response(results)
        body["messages"] = messages
        headers = {"x-saaf-entities": _summary_header(results), "x-saaf-mode": saaf.policy.mode}
        fwd = _forward_headers(request, OPENAI_FORWARD)
        url = f"{upstream}/v1/chat/completions"

        if body.get("stream"):
            req = gw.client.build_request("POST", url, json=body, headers=fwd)
            resp = await gw.client.send(req, stream=True)
            if resp.status_code >= 400:
                content = await resp.aread()
                await resp.aclose()
                return Response(content, resp.status_code, media_type=resp.headers.get("content-type"))

            async def gen() -> AsyncIterator[bytes]:
                try:
                    async for chunk in restore_openai_stream(saaf, _lines(resp)):
                        yield chunk
                finally:
                    await resp.aclose()

            return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)

        resp = await gw.client.post(url, json=body, headers=fwd)
        try:
            data = resp.json()
        except ValueError:
            return Response(resp.content, resp.status_code, media_type=resp.headers.get("content-type"))
        for choice in data.get("choices") or []:
            msg = choice.get("message") or {}
            if isinstance(msg.get("content"), str):
                msg["content"] = saaf.restore(msg["content"]).text
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                if isinstance(fn.get("arguments"), str):
                    fn["arguments"] = saaf.restore_json(fn["arguments"])
        return JSONResponse(data, resp.status_code, headers=headers)

    @app.post("/v1/messages")
    async def messages(request: Request) -> Response:
        body = await request.json()
        saaf, tenant = gw.session(request)
        upstream = gw.config.upstream_anthropic
        dest = urlparse(upstream).hostname or upstream
        results: list[MaskResult] = []
        system = body.get("system")
        if isinstance(system, str):
            r = saaf.mask(system, destination=dest)
            results.append(r)
            body["system"] = r.text
        elif isinstance(system, list):
            masked_system, rs = saaf.mask_messages([{"content": system}], destination=dest)
            body["system"] = masked_system[0]["content"]
            results.extend(rs)
        msgs, rs = saaf.mask_messages(body.get("messages") or [], destination=dest)
        results.extend(rs)
        _record(gw, saaf, tenant, results, dest, "messages")
        if any(r.blocked for r in results):
            return _blocked_response(results)
        body["messages"] = msgs
        headers = {"x-saaf-entities": _summary_header(results), "x-saaf-mode": saaf.policy.mode}
        fwd = _forward_headers(request, ANTHROPIC_FORWARD)
        url = f"{upstream}/v1/messages"

        if body.get("stream"):
            req = gw.client.build_request("POST", url, json=body, headers=fwd)
            resp = await gw.client.send(req, stream=True)
            if resp.status_code >= 400:
                content = await resp.aread()
                await resp.aclose()
                return Response(content, resp.status_code, media_type=resp.headers.get("content-type"))

            async def gen() -> AsyncIterator[bytes]:
                try:
                    async for chunk in restore_anthropic_stream(saaf, _lines(resp)):
                        yield chunk
                finally:
                    await resp.aclose()

            return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)

        resp = await gw.client.post(url, json=body, headers=fwd)
        try:
            data = resp.json()
        except ValueError:
            return Response(resp.content, resp.status_code, media_type=resp.headers.get("content-type"))
        for block in data.get("content") or []:
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                block["text"] = saaf.restore(block["text"]).text
            elif block.get("type") == "tool_use" and "input" in block:
                block["input"] = saaf.restore_json(block["input"])
        return JSONResponse(data, resp.status_code, headers=headers)

    return app
