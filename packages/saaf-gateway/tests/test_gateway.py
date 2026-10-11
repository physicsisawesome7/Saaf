from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from saaf import verify_chain
from saaf.audit import read_jsonl
from saaf_gateway import GatewayConfig, create_app

PAN = "ABCPE1234F"
AADHAAR = "2345 6789 0124"


class Upstream:
    """Mock provider. Records what it received; replies with canned output."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.headers: list[httpx.Headers] = []
        self.reply_text = "Your PAN is [PAN_1] and Aadhaar [AADHAAR_1]."
        self.stream_chunks = ["Your PAN is [PA", "N_1] and Aad", "haar [AADHAAR", "_1]."]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        self.headers.append(request.headers)
        if request.url.path == "/v1/chat/completions":
            return self._openai(body)
        return self._anthropic(body)

    def _openai(self, body: dict[str, Any]) -> httpx.Response:
        if not body.get("stream"):
            return httpx.Response(
                200,
                json={
                    "id": "c1",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": self.reply_text,
                                "tool_calls": [
                                    {
                                        "id": "t",
                                        "type": "function",
                                        "function": {"name": "kyc", "arguments": json.dumps({"pan": "[PAN_1]"})},
                                    }
                                ],
                            },
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        events = []
        for i, chunk in enumerate(self.stream_chunks):
            last = i == len(self.stream_chunks) - 1
            events.append(
                {
                    "id": "c1",
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": "stop" if last else None}],
                }
            )
        sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})

    def _anthropic(self, body: dict[str, Any]) -> httpx.Response:
        if not body.get("stream"):
            return httpx.Response(
                200,
                json={
                    "id": "m1",
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": self.reply_text},
                        {"type": "tool_use", "id": "tu", "name": "kyc", "input": {"pan": "[PAN_1]"}},
                    ],
                },
            )
        evs = [
            ("message_start", {"type": "message_start", "message": {"id": "m1"}}),
            (
                "content_block_start",
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            ),
        ]
        evs += [
            (
                "content_block_delta",
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": c}},
            )
            for c in self.stream_chunks
        ]
        evs += [
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_stop", {"type": "message_stop"}),
        ]
        sse = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in evs)
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def make_client(upstream: Upstream, tmp_path):
    def make(**cfg: Any) -> TestClient:
        config = GatewayConfig(
            upstream_openai="https://openai.test", upstream_anthropic="https://anthropic.test", **cfg
        )
        return TestClient(create_app(config, transport=httpx.MockTransport(upstream)))

    return make


USER_MSG = {"role": "user", "content": f"My PAN is {PAN} and aadhaar {AADHAAR}"}


def _sse_text(raw: str, field: str) -> str:
    out = []
    for block in raw.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: ") and line[6:] != "[DONE]":
                obj = json.loads(line[6:])
                if field == "openai":
                    for ch in obj.get("choices", []):
                        out.append(ch.get("delta", {}).get("content") or "")
                elif obj.get("type") == "content_block_delta":
                    out.append(obj["delta"].get("text", ""))
    return "".join(out)


def test_openai_masks_upstream_and_restores_reply(make_client, upstream: Upstream) -> None:
    c = make_client()
    r = c.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [USER_MSG]},
        headers={"authorization": "Bearer sk-test", "cookie": "secret"},
    )
    assert r.status_code == 200
    sent = json.dumps(upstream.requests[0])
    assert PAN not in sent and "2345" not in sent and "[PAN_1]" in sent
    assert upstream.headers[0]["authorization"] == "Bearer sk-test"
    assert "cookie" not in upstream.headers[0]
    msg = r.json()["choices"][0]["message"]
    assert msg["content"] == f"Your PAN is {PAN} and Aadhaar {AADHAAR}."
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"pan": PAN}
    assert r.headers["x-saaf-entities"] == "AADHAAR=1,PAN=1"


def test_openai_stream_restores_split_tokens(make_client) -> None:
    c = make_client()
    with c.stream("POST", "/v1/chat/completions", json={"model": "m", "stream": True, "messages": [USER_MSG]}) as r:
        raw = "".join(r.iter_text())
    assert _sse_text(raw, "openai") == f"Your PAN is {PAN} and Aadhaar {AADHAAR}."
    assert raw.rstrip().endswith("data: [DONE]")


def test_anthropic_masks_system_and_restores(make_client, upstream: Upstream) -> None:
    c = make_client()
    r = c.post(
        "/v1/messages",
        json={"model": "m", "max_tokens": 10, "system": f"Customer PAN {PAN}", "messages": [USER_MSG]},
        headers={"x-api-key": "k", "anthropic-version": "2023-06-01"},
    )
    assert r.status_code == 200
    sent = upstream.requests[0]
    assert sent["system"] == "Customer PAN [PAN_1]"
    assert upstream.headers[0]["x-api-key"] == "k"
    blocks = r.json()["content"]
    assert blocks[0]["text"] == f"Your PAN is {PAN} and Aadhaar {AADHAAR}."
    assert blocks[1]["input"] == {"pan": PAN}


def test_anthropic_stream_flushes_before_block_stop(make_client) -> None:
    c = make_client()
    with c.stream(
        "POST", "/v1/messages", json={"model": "m", "max_tokens": 10, "stream": True, "messages": [USER_MSG]}
    ) as r:
        raw = "".join(r.iter_text())
    assert _sse_text(raw, "anthropic") == f"Your PAN is {PAN} and Aadhaar {AADHAAR}."
    assert raw.index("content_block_stop") > raw.rindex("text_delta")


def test_block_policy_returns_403_without_calling_upstream(make_client, upstream: Upstream, tmp_path) -> None:
    (tmp_path / "strict.toml").write_text('[entities.AADHAAR]\naction = "block"\n', encoding="utf-8")
    c = make_client(policy_dir=tmp_path)
    r = c.post("/v1/chat/completions", json={"messages": [USER_MSG]}, headers={"x-saaf-tenant": "strict"})
    assert r.status_code == 403
    assert r.json()["error"]["entities"] == ["AADHAAR"]
    assert upstream.requests == []


def test_shadow_tenant_forwards_unchanged(make_client, upstream: Upstream, tmp_path) -> None:
    (tmp_path / "pilot.toml").write_text('[policy]\nmode = "shadow"\n', encoding="utf-8")
    c = make_client(policy_dir=tmp_path)
    r = c.post("/v1/chat/completions", json={"messages": [USER_MSG]}, headers={"x-saaf-tenant": "pilot"})
    assert r.status_code == 200
    assert upstream.requests[0]["messages"][0]["content"] == USER_MSG["content"]
    assert r.headers["x-saaf-mode"] == "shadow"


def test_invalid_tenant_rejected(make_client) -> None:
    r = make_client().post("/v1/chat/completions", json={"messages": []}, headers={"x-saaf-tenant": "../etc"})
    assert r.status_code == 400


def test_audit_log_counts_only(make_client, tmp_path) -> None:
    key = os.urandom(32)
    log = tmp_path / "audit.jsonl"
    c = make_client(audit_log=log, audit_key=key)
    c.post("/v1/chat/completions", json={"messages": [USER_MSG]})
    c.post("/v1/messages", json={"messages": [USER_MSG]})
    records = read_jsonl(log)
    assert len(records) == 2 and verify_chain(records, key)[0]
    assert records[0]["entity_counts"] == {"AADHAAR": 1, "PAN": 1}
    assert PAN not in log.read_text(encoding="utf-8")


def test_scan_endpoint_never_returns_values(make_client) -> None:
    r = make_client().post("/v1/saaf/scan", json={"text": f"PAN {PAN}"})
    assert r.json()["findings"][0]["entity"] == "PAN"
    assert PAN not in r.text


def test_upstream_error_passthrough(make_client, upstream: Upstream) -> None:
    upstream._openai = lambda body: httpx.Response(429, json={"error": {"message": "rate limited"}})  # type: ignore[method-assign]
    r = make_client().post("/v1/chat/completions", json={"messages": [USER_MSG], "stream": True})
    assert r.status_code == 429
