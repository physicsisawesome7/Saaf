"""LangChain integration.

``with_saaf(model)``
    Wrap any chat model / runnable: inputs are masked, outputs restored. One
    Saaf session per invocation, so concurrent calls never share tokens.

``mask_documents(docs)``
    Mask ``page_content`` before embedding and indexing in a RAG pipeline.
    Uses keyed-HMAC tokens so the same value gets the same token in every
    chunk and every run (given the same key), which keeps retrieval consistent.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from typing import Any

from saaf import Policy, Saaf

__version__ = "0.1.0.dev0"
__all__ = ["mask_documents", "with_saaf"]


def _mask_input(saaf: Saaf, value: Any) -> Any:
    from langchain_core.messages import BaseMessage
    from langchain_core.prompt_values import PromptValue

    if isinstance(value, PromptValue):
        value = value.to_messages()
    if isinstance(value, str):
        return saaf.mask(value).text
    if isinstance(value, BaseMessage):
        return _mask_message(saaf, value)
    if isinstance(value, Sequence):
        return [_mask_input(saaf, v) for v in value]
    if isinstance(value, dict):
        return saaf.mask_json(value)
    return value


def _mask_message(saaf: Saaf, msg: Any) -> Any:
    content = msg.content
    if isinstance(content, str):
        content = saaf.mask(content).text
    elif isinstance(content, list):
        content = [
            {**p, "text": saaf.mask(p["text"]).text} if isinstance(p, dict) and isinstance(p.get("text"), str) else p
            for p in content
        ]
    return msg.model_copy(update={"content": content})


def _restore_output(saaf: Saaf, value: Any) -> Any:
    from langchain_core.messages import BaseMessage

    if isinstance(value, str):
        return saaf.restore(value).text
    if isinstance(value, BaseMessage):
        update: dict[str, Any] = {}
        if isinstance(value.content, str):
            update["content"] = saaf.restore(value.content).text
        tool_calls = getattr(value, "tool_calls", None)
        if tool_calls:
            update["tool_calls"] = [{**tc, "args": saaf.restore_json(tc.get("args", {}))} for tc in tool_calls]
        return value.model_copy(update=update)
    return value


def with_saaf(runnable: Any, policy: Policy | None = None) -> Any:
    """Return a runnable that masks inputs to ``runnable`` and restores its output."""
    from langchain_core.runnables import RunnableLambda

    pol = policy or Policy()

    def invoke(value: Any, config: Any = None) -> Any:
        saaf = Saaf(pol)
        masked = _mask_input(saaf, value)
        return _restore_output(saaf, runnable.invoke(masked, config))

    async def ainvoke(value: Any, config: Any = None) -> Any:
        saaf = Saaf(pol)
        masked = _mask_input(saaf, value)
        return _restore_output(saaf, await runnable.ainvoke(masked, config))

    return RunnableLambda(invoke, afunc=ainvoke, name="saaf")


def mask_documents(docs: Iterable[Any], *, key: bytes | None = None, policy: Policy | None = None) -> list[Any]:
    """Mask ``page_content`` of LangChain ``Document`` objects for indexing.

    ``key`` (32 bytes, or hex in ``SAAF_INDEX_KEY``) makes tokens stable across
    runs; keep it secret, since anyone holding it can test guesses against tokens.
    """
    env = os.environ.get("SAAF_INDEX_KEY")
    k = key or (bytes.fromhex(env) if env else None)
    base = policy or Policy()
    pol = Policy(**{**base.__dict__, "token_style": "hmac"})
    saaf = Saaf(pol, hmac_key=k)
    out = []
    for d in docs:
        r = saaf.mask(d.page_content)
        meta = {**(d.metadata or {}), "saaf_entities": r.entity_counts}
        out.append(d.model_copy(update={"page_content": r.text, "metadata": meta}))
    return out
