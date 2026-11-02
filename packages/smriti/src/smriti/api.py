"""HTTP API: REST for the web app, SSE streaming, and an OpenAI-compatible
endpoint so existing chat clients, IDEs and workflow tools plug straight in.

Handlers are plain ``def`` so FastAPI runs them in its thread pool; the API is
stateless apart from the per-tenant index, so it scales out behind a load
balancer (each replica rebuilds its local index from the store, or all share
Qdrant).
"""

from __future__ import annotations

import difflib
import json
import random
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, evals, memory, skills, watch
from .access import UnknownUser, evaluate
from .ask import ask, ask_stream
from .config import Settings, load_pack
from .engine import Tenant
from .models import Principal
from .store import Store, feedback, make_blob_store, traces

WEB_DIR = Path(__file__).parent / "web"


class AskBody(BaseModel):
    question: str
    as_of: str | None = None
    history: list[dict[str, str]] | None = None


class FeedbackBody(BaseModel):
    trace_id: str
    rating: int
    chunk_id: str | None = None
    comment: str | None = None


class DraftAction(BaseModel):
    action: str
    content: str | None = None


class MemoryBody(BaseModel):
    text: str
    tier: str = "user"
    provenance: list[str] = []


class Platform:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(settings.database_url)
        self.blobs = make_blob_store(settings.blob_url, settings.data_dir)
        self.tenants: dict[str, Tenant] = {}
        for path in settings.packs:
            pack = load_pack(path)
            self.tenants[pack.id] = Tenant(pack, self.store, self.blobs, settings)
        self.default = settings.default_tenant or next(iter(self.tenants))
        self.demo_published: set[str] = set()
        self.scheduler: watch.Scheduler | None = None

    def tenant(self, tid: str | None) -> Tenant:
        t = self.tenants.get(tid or self.default)
        if not t:
            raise HTTPException(404, f"unknown tenant {tid}")
        return t


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    plat = Platform(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.scheduler and any(s.schedule for t in plat.tenants.values() for s in t.pack.sources):
            plat.scheduler = watch.Scheduler(plat.tenants)
            plat.scheduler.start()
        yield
        if plat.scheduler:
            plat.scheduler.stop()

    app = FastAPI(
        title="Smriti by Safearly",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.platform = plat

    # ------------------------------------------------------------ identity

    def ctx(
        request: Request,
        x_smriti_user: str | None = Header(default=None),
        x_smriti_tenant: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ) -> tuple[Tenant, Principal]:
        t = plat.tenant(x_smriti_tenant or request.query_params.get("tenant"))
        user = None
        if settings.auth_mode == "token":
            tok = (authorization or "").removeprefix("Bearer ").strip()
            user = settings.api_tokens.get(tok)
            if not user:
                raise HTTPException(401, "invalid or missing bearer token")
        else:  # demo directory: the web app's "view as" switcher sets this header
            user = (
                x_smriti_user
                or request.query_params.get("as")
                or (t.pack.roles.users[0].id if t.pack.roles.users else None)
            )
        try:
            return t, t.principal(user or "")
        except UnknownUser:
            raise HTTPException(401, f"unknown user {user}") from None

    def need(p: Principal, *grants: str) -> None:
        if not any(p.can(g) for g in grants):
            raise HTTPException(403, f"needs one of: {', '.join(grants)}")

    # ------------------------------------------------------------ meta

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "tenants": list(plat.tenants)}

    @app.get("/api/whoami")
    def whoami(c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        return {
            "tenant": {"id": t.id, "name": t.pack.config.name},
            "user": {
                "id": p.user_id,
                "name": p.name,
                "roles": p.roles,
                "grants": sorted(p.grants),
                "divisions": p.divisions,
                "projects": p.projects,
                "groups": [g for g in p.groups if not g.startswith("user:")],
                "clearance": p.clearance,
                "unmask": sorted(p.unmask),
            },
            "directory": [{"id": u.id, "name": u.name, "title": u.title, "roles": u.roles} for u in t.pack.roles.users]
            if settings.auth_mode == "demo"
            else [],
        }

    @app.get("/api/stats")
    def stats(c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        docs = t.store.list_documents(t.id)
        visible = [d for d in docs if evaluate(p, d["access"], d["doc_type"]).allowed]
        return {
            "documents_total": len(docs),
            "documents_visible": len(visible),
            "chunks_indexed": len(t.index),
            "sources": len(t.pack.sources),
            "skills": len(t.pack.skills),
            "models": t.gw.describe()
            | {"embedder": t.embedder.name, "reranker": t.reranker.name, "vector_backend": settings.vector_backend},
            "usage": t.gw.usage.__dict__,
            "audit_records": t.audit.verify()["records"] if p.can("audit") or p.can("administer") else None,
        }

    # ------------------------------------------------------------ ask

    @app.post("/api/ask")
    def api_ask(body: AskBody, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        need(p, "view")
        return ask(t, p, body.question, as_of=body.as_of or None, history=body.history)

    @app.post("/api/ask/stream")
    def api_ask_stream(body: AskBody, c: tuple[Tenant, Principal] = Depends(ctx)) -> StreamingResponse:
        t, p = c
        need(p, "view")

        def gen():  # type: ignore[no-untyped-def]
            for ev in ask_stream(t, p, body.question, as_of=body.as_of or None, history=body.history):
                if ev["event"] == "final":
                    ans = ev["data"]["answer"]
                    # offline writer: stream the verified answer word by word for a responsive UI
                    if (ev["data"].get("model") or "").startswith(("extractive", "computed")) or ev["data"].get(
                        "abstained"
                    ):
                        for i, w in enumerate(ans.split(" ")):
                            yield f"event: token\ndata: {json.dumps((' ' if i else '') + w)}\n\n"
                            time.sleep(0.008)
                yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], default=str)}\n\n"

        return StreamingResponse(
            gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    @app.get("/api/search")
    def api_search(q: str, as_of: str | None = None, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        need(p, "view")
        ps, tr = t.retrieve(p, q, as_of=as_of, top_k=15)
        tr.pop("qtokens", None)
        t.audit.record(p.user_id, "search", query=q[:200], results=[x.doc_id for x in ps])
        return {"results": [x.__dict__ for x in ps], "trace": tr}

    @app.post("/api/feedback")
    def api_feedback(body: FeedbackBody, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        t.store.insert(
            feedback,
            tenant=t.id,
            user_id=p.user_id,
            trace_id=body.trace_id,
            rating=body.rating,
            chunk_id=body.chunk_id,
            comment=(body.comment or "")[:2000],
            created_at=time.time(),
        )
        t.audit.record(p.user_id, "feedback", trace_id=body.trace_id, rating=body.rating, wrong_source=body.chunk_id)
        return {"ok": True}

    @app.get("/api/traces/{trace_id}")
    def api_trace(trace_id: str, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        rows = t.store.rows(traces, tenant=t.id, trace_id=trace_id)
        if not rows or (rows[0]["user_id"] != p.user_id and not (p.can("audit") or p.can("administer"))):
            raise HTTPException(404)
        return {**rows[0], "data": json.loads(rows[0]["data"])}

    # ------------------------------------------------------------ documents

    def _doc_view(t: Tenant, p: Principal, d: dict[str, Any]) -> dict[str, Any]:
        ok = evaluate(p, d["access"], d["doc_type"]).allowed
        out = {
            k: d[k]
            for k in (
                "doc_id",
                "title",
                "doc_type",
                "ref_no",
                "doc_date",
                "status",
                "current_version",
                "source",
                "source_url",
            )
        }
        out["doc_class"] = d["access"]["doc_class"]
        out["access"] = d["access"]
        out["readable"] = ok
        out["effective_from"] = d["meta"].get("effective_from")
        out["low_confidence"] = d["meta"].get("low_confidence")
        out["lang"] = d["meta"].get("lang")
        out["injection_blocks"] = d["meta"].get("injection_blocks")
        out["legal_status"] = d["meta"].get("legal_status")
        out["warnings"] = d["meta"].get("warnings")
        return out

    @app.get("/api/documents")
    def api_docs(c: tuple[Tenant, Principal] = Depends(ctx)) -> list[dict[str, Any]]:
        t, p = c
        docs = [d for d in t.store.list_documents(t.id) if d["status"] != "tombstoned"]
        if p.can("administer"):  # admins manage metadata; content stays hidden unless they also have 'view'
            return [_doc_view(t, p, d) for d in docs]
        return [_doc_view(t, p, d) for d in docs if evaluate(p, d["access"], d["doc_type"]).allowed]

    @app.get("/api/documents/{doc_id}")
    def api_doc(doc_id: str, version: int | None = None, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        d = t.store.get_document(t.id, doc_id)
        if not d or not evaluate(p, d["access"], d["doc_type"]).allowed:
            raise HTTPException(404, "not found")  # never confirm that a hidden document exists
        chunks = t.store.doc_chunks(t.id, doc_id, version)
        chunks.sort(key=lambda c: (c["page"] or 0, c["first_version"]))
        rels = []
        for r in t.store.relations_for(t.id, doc_id):
            other_id = r["dst_doc"] if r["src_doc"] == doc_id else r["src_doc"]
            other = t.store.get_document(t.id, other_id) if other_id else None
            if other and not evaluate(p, other["access"], other["doc_type"]).allowed:
                continue
            rels.append(
                {
                    **r,
                    "direction": "out" if r["src_doc"] == doc_id else "in",
                    "other_title": other["title"] if other else r["dst_ref"],
                    "other_id": other_id,
                }
            )
        impact = [x for x in t.impact_of(doc_id) if evaluate(p, x["access"], x["doc_type"]).allowed]
        for x in impact:
            x.pop("access", None)
        t.audit.record(p.user_id, "open_document", doc_id=doc_id, version=version)
        return {
            **_doc_view(t, p, d),
            "versions": [
                {
                    k: v[k]
                    for k in (
                        "version",
                        "sha256",
                        "filename",
                        "mime",
                        "parser",
                        "effective_from",
                        "ingested_at",
                        "pages",
                        "low_confidence",
                    )
                }
                for v in t.store.get_versions(t.id, doc_id)
            ],
            "chunks": [
                {
                    "chunk_id": ch["chunk_id"],
                    "section": " > ".join(ch["section_path"]),
                    "clause_id": ch["clause_id"],
                    "page": ch["page"],
                    "kind": ch["kind"],
                    "text": t.render_for(p, ch, d)[0],
                    "confidence": ch["confidence"],
                }
                for ch in chunks
            ],
            "relations": rels,
            "impact": impact,
        }

    @app.get("/api/documents/{doc_id}/diff")
    def api_diff(doc_id: str, a: int, b: int, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        d = t.store.get_document(t.id, doc_id)
        if not d or not evaluate(p, d["access"], d["doc_type"]).allowed:
            raise HTTPException(404)

        def text(v: int) -> list[str]:
            return [t.render_for(p, ch, d)[0] for ch in t.store.doc_chunks(t.id, doc_id, v)]

        ta, tb = text(a), text(b)
        diff = list(
            difflib.unified_diff(
                "\n".join(ta).splitlines(), "\n".join(tb).splitlines(), f"v{a}", f"v{b}", lineterm="", n=1
            )
        )
        return {
            "a": a,
            "b": b,
            "diff": diff,
            "added": sum(1 for x in diff if x.startswith("+") and not x.startswith("+++")),
            "removed": sum(1 for x in diff if x.startswith("-") and not x.startswith("---")),
        }

    @app.get("/api/documents/{doc_id}/raw")
    def api_raw(doc_id: str, version: int | None = None, c: tuple[Tenant, Principal] = Depends(ctx)) -> Response:
        t, p = c
        d = t.store.get_document(t.id, doc_id)
        if not d or not evaluate(p, d["access"], d["doc_type"]).allowed:
            raise HTTPException(404)
        if d["access"].get("pii") and not set(d["access"]["pii"]) <= {u.lower() for u in p.unmask}:
            raise HTTPException(
                403, "the original file contains personal data your role cannot unmask; use the masked view"
            )
        vs = t.store.get_versions(t.id, doc_id)
        v = next((x for x in vs if x["version"] == (version or d["current_version"])), vs[-1])
        t.audit.record(p.user_id, "download_original", doc_id=doc_id, version=v["version"])
        return Response(
            t.blobs.get(v["blob_key"]),
            media_type=v["mime"] if "/" in (v["mime"] or "") else "application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{v["filename"]}"'},
        )

    @app.get("/api/documents/{doc_id}/access")
    def api_access(doc_id: str, user: str, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        """Role simulator: why can (or can't) this person see this document?"""
        t, p = c
        if user != p.user_id:
            need(p, "administer", "audit", "curate")
        d = t.store.get_document(t.id, doc_id)
        if not d:
            raise HTTPException(404)
        dec = t.authz.explain(t.principal(user), d)
        return {"user": user, "doc_id": doc_id, "allowed": dec.allowed, "reasons": dec.reasons}

    @app.post("/api/documents")
    def api_upload(
        file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency idiom
        doc_class: str = Form("internal"),
        divisions: str = Form("*"),
        projects: str = Form(""),
        groups: str = Form(""),
        doc_type: str = Form(""),
        c: tuple[Tenant, Principal] = Depends(ctx),
    ) -> dict[str, Any]:
        t, p = c
        need(p, "upload")
        data = file.file.read()
        hints: dict[str, Any] = {
            "access": {
                "doc_class": doc_class,
                "divisions": [x.strip() for x in divisions.split(",") if x.strip()] or ["*"],
                "projects": [x.strip() for x in projects.split(",") if x.strip()],
                "groups": [x.strip() for x in groups.split(",") if x.strip()],
            }
        }
        if doc_type:
            hints["doc_type"] = doc_type
        try:
            return t.ingest(data, file.filename or "upload.bin", actor=p.user_id, hints=hints)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    # ------------------------------------------------------------ watch

    @app.get("/api/sources")
    def api_sources(c: tuple[Tenant, Principal] = Depends(ctx)) -> list[dict[str, Any]]:
        t, _ = c
        return watch.source_health(t)

    @app.post("/api/sources/{name}/run")
    def api_run_source(name: str, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        need(p, "curate", "administer")
        try:
            rep = watch.run_source(t, name, actor=p.user_id)
        except KeyError:
            raise HTTPException(404, "unknown source") from None
        for k in ("new", "changed"):
            for e in rep[k]:
                e["impact"] = [x for x in e.get("impact", []) if evaluate(p, x["access"], x["doc_type"]).allowed]
                for x in e["impact"]:
                    x.pop("access", None)
        rep["impact"] = [x for k in ("new", "changed") for e in rep[k] for x in e["impact"]]
        return rep

    @app.get("/api/alerts")
    def api_alerts(c: tuple[Tenant, Principal] = Depends(ctx)) -> list[dict[str, Any]]:
        t, p = c
        return watch.visible_alerts(t, p)

    # ------------------------------------------------------------ skills

    @app.get("/api/skills")
    def api_skills(c: tuple[Tenant, Principal] = Depends(ctx)) -> list[dict[str, Any]]:
        t, p = c
        return skills.list_skills(t, p)

    @app.post("/api/skills/{name}/run")
    def api_skill(name: str, inputs: dict[str, Any], c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        try:
            return skills.run_skill(t, p, name, inputs)
        except KeyError:
            raise HTTPException(404, "unknown skill") from None
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e

    @app.get("/api/drafts")
    def api_drafts(c: tuple[Tenant, Principal] = Depends(ctx)) -> list[dict[str, Any]]:
        t, p = c
        return skills.list_drafts(t, p)

    @app.post("/api/drafts/{draft_id}")
    def api_draft(draft_id: int, body: DraftAction, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        try:
            return skills.update_draft(t, p, draft_id, body.action, body.content)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        except KeyError:
            raise HTTPException(404) from None

    # ------------------------------------------------------------ memory

    @app.get("/api/memories")
    def api_memories(c: tuple[Tenant, Principal] = Depends(ctx)) -> list[dict[str, Any]]:
        t, p = c
        return memory.visible(t, p)

    @app.post("/api/memories")
    def api_mem_add(body: MemoryBody, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        try:
            return memory.propose(t, p, body.text, body.tier, body.provenance)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e

    @app.post("/api/memories/{mid}/review")
    def api_mem_review(mid: int, approve: bool, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        try:
            return memory.review(t, p, mid, approve)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e

    @app.delete("/api/memories/{mid}")
    def api_mem_del(mid: int, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        try:
            memory.delete(t, p, mid)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        return {"ok": True}

    # ------------------------------------------------------------ govern

    @app.get("/api/audit")
    def api_audit(limit: int = 100, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        need(p, "audit", "administer")
        return {"verify": t.audit.verify(), "records": t.audit.tail(min(limit, 500))}

    @app.get("/api/policy")
    def api_policy(c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, _ = c
        return {
            "guardrails": t.pack.guardrails,
            "roles": {k: v.model_dump() for k, v in t.pack.roles.roles.items()},
            "glossary": t.pack.glossary,
            "models": t.gw.describe(),
            "pack_layers": [str(r.name) for r in t.pack.roots],
        }

    @app.post("/api/evals/{kind}")
    def api_evals(kind: str, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        t, p = c
        need(p, "administer", "curate", "audit")
        if kind == "golden":
            return evals.run_golden(t)
        if kind == "leakage":
            return evals.leakage_suite(t)
        if kind == "redteam":
            return evals.redteam(t)
        if kind == "gate":
            return evals.release_gate(t)
        if kind.startswith("skill:"):
            return skills.eval_skill(t, kind.split(":", 1)[1])
        raise HTTPException(404)

    @app.get("/api/simulate")
    def api_simulate(user: str, q: str, c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        """'View as user X': which documents X would retrieve for a query, and why others are hidden."""
        t, p = c
        need(p, "administer", "audit", "curate")
        target = t.principal(user)
        ps, _ = t.retrieve(target, q, include_superseded=True)
        seen = {x.doc_id for x in ps}
        hidden = []
        for d in t.store.list_documents(t.id):
            dec = t.authz.explain(target, d)
            if not dec.allowed:
                hidden.append({"doc_id": d["doc_id"], "title": d["title"], "reasons": dec.reasons})
        t.audit.record(p.user_id, "simulate", target=user, query=q[:200])
        return {
            "user": user,
            "would_retrieve": [{"doc_id": x.doc_id, "title": x.title, "status": x.status} for x in ps],
            "visible_docs": len(seen),
            "hidden": hidden,
        }

    # ------------------------------------------------------------ OpenAI-compatible

    @app.get("/v1/models")
    def v1_models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [{"id": f"smriti/{tid}", "object": "model", "owned_by": "safearly"} for tid in plat.tenants],
        }

    @app.post("/v1/chat/completions")
    def v1_chat(
        body: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
        x_smriti_user: str | None = Header(default=None),
    ) -> Any:
        model = str(body.get("model") or "")
        tid = model.split("/", 1)[1] if model.startswith("smriti/") else None
        t, p = ctx(request, x_smriti_user, tid, authorization)
        msgs = body.get("messages") or []
        question = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), "")
        if isinstance(question, list):
            question = " ".join(x.get("text", "") for x in question if isinstance(x, dict))
        history = [m for m in msgs[:-1] if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
        res = ask(t, p, question, history=history or None)
        content = res["answer"]
        if res["citations"]:
            content += "\n\nSources:\n" + "\n".join(
                f"[{c['n']}] {c['title']}"
                + (f" ({c['ref_no']})" if c["ref_no"] else "")
                + (f", clause {c['clause_id']}" if c["clause_id"] else "")
                + f", p.{c['page']}"
                for c in res["citations"]
            )
        cid = "chatcmpl-" + uuid.uuid4().hex[:20]
        created = int(time.time())
        if body.get("stream"):

            def gen():  # type: ignore[no-untyped-def]
                for i in range(0, len(content), 48):
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "id": cid,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model or "smriti",
                                "choices": [
                                    {"index": 0, "delta": {"content": content[i : i + 48]}, "finish_reason": None}
                                ],
                            }
                        )
                        + "\n\n"
                    )
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "id": cid,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model or "smriti",
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                        }
                    )
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")
        return {
            "id": cid,
            "object": "chat.completion",
            "created": created,
            "model": model or "smriti",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "smriti": {
                "trace_id": res["trace_id"],
                "abstained": res["abstained"],
                "citations": res["citations"],
                "verification": res["verification"],
            },
        }

    # ------------------------------------------------------------ demo site (crawler target)

    @app.get("/demo-site/circulars", response_class=HTMLResponse)
    def demo_listing(request: Request) -> str:
        t = plat.tenant(request.query_params.get("tenant"))
        root = t.pack.resolve("demo-site")
        if not root:
            raise HTTPException(404)
        items = yaml.safe_load((root / "listing.yaml").read_text(encoding="utf-8"))["items"]
        rows = []
        sid = uuid.uuid4().hex[:24]
        for it in items:
            if not it.get("published", True) and it["file"] not in plat.demo_published:
                continue
            rows.append(
                f'<tr><td>{it["ref"]}</td><td>{it["title"]}</td><td>{it["date"]}</td><td><a href="/demo-site/files/{it["file"]}?sid={sid}">Download</a></td></tr>'
            )
        return f"""<!doctype html><html><head><title>Board circulars (demo)</title></head><body>
<h1>Railway Board circulars (synthetic demo site)</h1>
<p class="counter">Visitors: {random.randint(10000, 99999)}</p>
<table class="circulars"><tr><th>No.</th><th>Subject</th><th>Date</th><th>File</th></tr>{"".join(rows)}</table>
<p>Last updated: {time.strftime("%d %b %Y %H:%M:%S")}</p></body></html>"""

    @app.get("/demo-site/files/{name}")
    def demo_file(name: str, request: Request) -> FileResponse:
        t = plat.tenant(request.query_params.get("tenant"))
        root = t.pack.resolve("demo-site/files")
        f = (root / name).resolve() if root else None
        if not f or not root or root.resolve() not in f.parents or not f.exists():
            raise HTTPException(404)
        return FileResponse(f)

    @app.get("/robots.txt", response_class=Response)
    def robots() -> Response:
        return Response("User-agent: *\nAllow: /demo-site/\nDisallow: /api/\n", media_type="text/plain")

    @app.post("/api/demo/publish")
    def demo_publish(c: tuple[Tenant, Principal] = Depends(ctx)) -> dict[str, Any]:
        """Simulates the Board publishing the next pending circular on the demo site."""
        t, p = c
        need(p, "curate", "administer")
        root = t.pack.resolve("demo-site")
        items = yaml.safe_load((root / "listing.yaml").read_text(encoding="utf-8"))["items"] if root else []
        pending = [i for i in items if not i.get("published", True) and i["file"] not in plat.demo_published]
        if not pending:
            return {"published": None, "message": "nothing left to publish"}
        plat.demo_published.add(pending[0]["file"])
        return {"published": pending[0]}

    # ------------------------------------------------------------ web app

    @app.exception_handler(PermissionError)
    def _perm(_: Request, e: PermissionError) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=403)

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/", response_class=HTMLResponse)
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return app
