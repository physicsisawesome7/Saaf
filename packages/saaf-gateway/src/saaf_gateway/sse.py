"""Server-sent-event helpers and streaming restore for both wire formats."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from saaf import Saaf, StreamRestorer


async def sse_events(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str | None, str]]:
    """Group SSE lines into ``(event, data)`` pairs."""
    event: str | None = None
    data: list[str] = []
    async for line in lines:
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = None, []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data:
        yield event, "\n".join(data)


def encode(data: str | dict[str, Any], event: str | None = None) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    head = f"event: {event}\n" if event else ""
    return f"{head}data: {payload}\n\n".encode()


async def restore_openai_stream(saaf: Saaf, lines: AsyncIterator[str]) -> AsyncIterator[bytes]:
    """Restore ``choices[].delta.content`` and tool-call ``arguments`` deltas.

    Tokens split across chunks are held back by a :class:`StreamRestorer` per
    choice (and per tool call), and flushed on ``finish_reason`` or ``[DONE]``.
    """
    restorers: dict[tuple[int, int | None], StreamRestorer] = {}
    last: dict[str, Any] | None = None

    def r(key: tuple[int, int | None]) -> StreamRestorer:
        return restorers.setdefault(key, saaf.stream_restorer())

    def flush_choice(idx: int) -> tuple[str, dict[int, str]]:
        text = restorers.pop((idx, None)).flush() if (idx, None) in restorers else ""
        tools = {k[1]: restorers.pop(k).flush() for k in [k for k in restorers if k[0] == idx and k[1] is not None]}
        return text, {k: v for k, v in tools.items() if v and k is not None}

    async for _event, data in sse_events(lines):
        if data.strip() == "[DONE]":
            for idx in sorted({k[0] for k in restorers}):
                text, tools = flush_choice(idx)
                if text or tools:
                    yield encode(_openai_tail_chunk(last, idx, text, tools))
            yield encode("[DONE]")
            continue
        try:
            obj = json.loads(data)
        except ValueError:
            yield encode(data)
            continue
        for choice in obj.get("choices") or []:
            idx = choice.get("index", 0)
            delta = choice.get("delta") or {}
            if isinstance(delta.get("content"), str):
                delta["content"] = r((idx, None)).feed(delta["content"])
            for tc in delta.get("tool_calls") or []:
                fn = tc.get("function") or {}
                if isinstance(fn.get("arguments"), str):
                    fn["arguments"] = r((idx, tc.get("index", 0))).feed(fn["arguments"])
            if choice.get("finish_reason"):
                text, tools = flush_choice(idx)
                if text:
                    delta["content"] = (delta.get("content") or "") + text
                for tc_index, tail in tools.items():
                    delta.setdefault("tool_calls", []).append({"index": tc_index, "function": {"arguments": tail}})
                choice["delta"] = delta
        last = obj
        yield encode(obj)


def _openai_tail_chunk(last: dict[str, Any] | None, idx: int, text: str, tools: dict[int, str]) -> dict[str, Any]:
    base = {k: v for k, v in (last or {}).items() if k in ("id", "object", "created", "model")}
    delta: dict[str, Any] = {}
    if text:
        delta["content"] = text
    if tools:
        delta["tool_calls"] = [{"index": i, "function": {"arguments": a}} for i, a in tools.items()]
    return {**base, "choices": [{"index": idx, "delta": delta, "finish_reason": None}]}


async def restore_anthropic_stream(saaf: Saaf, lines: AsyncIterator[str]) -> AsyncIterator[bytes]:
    """Restore ``text_delta`` and ``input_json_delta`` events per content block;
    flush held text as an extra delta just before ``content_block_stop``."""
    restorers: dict[int, tuple[str, StreamRestorer]] = {}
    async for event, data in sse_events(lines):
        try:
            obj = json.loads(data)
        except ValueError:
            yield encode(data, event)
            continue
        kind = obj.get("type")
        if kind == "content_block_delta":
            idx = obj.get("index", 0)
            delta = obj.get("delta") or {}
            field = (
                "text"
                if delta.get("type") == "text_delta"
                else "partial_json"
                if delta.get("type") == "input_json_delta"
                else None
            )
            if field and isinstance(delta.get(field), str):
                dtype, sr = restorers.setdefault(idx, (delta["type"], saaf.stream_restorer()))
                delta[field] = sr.feed(delta[field])
        elif kind == "content_block_stop":
            idx = obj.get("index", 0)
            if idx in restorers:
                dtype, sr = restorers.pop(idx)
                tail = sr.flush()
                if tail:
                    field = "text" if dtype == "text_delta" else "partial_json"
                    yield encode(
                        {"type": "content_block_delta", "index": idx, "delta": {"type": dtype, field: tail}},
                        "content_block_delta",
                    )
        yield encode(obj, event)
