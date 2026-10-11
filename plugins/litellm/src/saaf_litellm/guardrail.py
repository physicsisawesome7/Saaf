"""LiteLLM proxy guardrail: mask before the call, restore after it.

``config.yaml``::

    guardrails:
      - guardrail_name: saaf
        litellm_params:
          guardrail: saaf_litellm.guardrail.SaafGuardrail
          mode: [pre_call, post_call]
          default_on: true

Optional environment: ``SAAF_POLICY`` (path to a policy .toml).

Each call gets its own :class:`saaf.Saaf` session, keyed by ``litellm_call_id``
and kept in a bounded in-process map between the pre- and post-call hooks.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import AsyncGenerator
from typing import Any

from saaf import Policy, Saaf

try:  # pragma: no cover - exercised only with litellm installed
    from litellm.integrations.custom_guardrail import CustomGuardrail
except ImportError:  # pragma: no cover

    class CustomGuardrail:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.guardrail_name = kwargs.get("guardrail_name", "saaf")


class SaafBlockedError(ValueError):
    """Raised from the pre-call hook; LiteLLM turns it into a 400 for the caller."""


class SaafGuardrail(CustomGuardrail):
    MAX_SESSIONS = 10_000

    def __init__(self, policy: Policy | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        path = os.environ.get("SAAF_POLICY")
        self.policy = policy or (Policy.load(path) if path else Policy())
        self._sessions: OrderedDict[str, Saaf] = OrderedDict()

    # -- session bookkeeping ------------------------------------------------

    def _key(self, data: dict[str, Any]) -> str | None:
        key = data.get("litellm_call_id") or (data.get("metadata") or {}).get("litellm_call_id")
        return str(key) if key else None

    def _open(self, data: dict[str, Any]) -> Saaf:
        saaf = Saaf(self.policy)
        key = self._key(data)
        if key:
            self._sessions[key] = saaf
            while len(self._sessions) > self.MAX_SESSIONS:
                self._sessions.popitem(last=False)
        return saaf

    def _take(self, data: dict[str, Any]) -> Saaf | None:
        key = self._key(data)
        return self._sessions.pop(key, None) if key else None

    # -- hooks ----------------------------------------------------------------

    async def async_pre_call_hook(
        self, user_api_key_dict: Any, cache: Any, data: dict[str, Any], call_type: str
    ) -> dict[str, Any]:
        saaf = self._open(data)
        if "messages" in data:
            data["messages"], results = saaf.mask_messages(data["messages"], destination=data.get("model"))
        elif isinstance(data.get("input"), (str, list)):  # embeddings
            masked = saaf.mask_json(data["input"])
            data["input"], results = masked, []
        else:
            results = []
        if any(r.blocked for r in results):
            self._take(data)
            entities = sorted({a.finding.entity for r in results for a in r.applied if a.action == "block"})
            raise SaafBlockedError(f"Request blocked by Saaf data policy: {', '.join(entities)}")
        return data

    async def async_post_call_success_hook(self, data: dict[str, Any], user_api_key_dict: Any, response: Any) -> Any:
        saaf = self._take(data)
        if saaf is None:
            return response
        for choice in getattr(response, "choices", None) or []:
            message = getattr(choice, "message", None)
            if message is None:
                continue
            if isinstance(getattr(message, "content", None), str):
                message.content = saaf.restore(message.content).text
            for tc in getattr(message, "tool_calls", None) or []:
                fn = getattr(tc, "function", None)
                if fn is not None and isinstance(getattr(fn, "arguments", None), str):
                    fn.arguments = saaf.restore_json(fn.arguments)
        return response

    async def async_post_call_streaming_iterator_hook(
        self, user_api_key_dict: Any, response: Any, request_data: dict[str, Any]
    ) -> AsyncGenerator[Any, None]:
        saaf = self._take(request_data)
        if saaf is None:
            async for chunk in response:
                yield chunk
            return
        restorers: dict[int, Any] = {}
        last = None
        async for chunk in response:
            for choice in getattr(chunk, "choices", None) or []:
                idx = getattr(choice, "index", 0) or 0
                delta = getattr(choice, "delta", None)
                sr = restorers.setdefault(idx, saaf.stream_restorer())
                if delta is not None and isinstance(getattr(delta, "content", None), str):
                    delta.content = sr.feed(delta.content)
                if getattr(choice, "finish_reason", None) and delta is not None:
                    tail = restorers.pop(idx).flush()
                    if tail:
                        delta.content = (delta.content or "") + tail
            last = chunk
            yield chunk
        if restorers and last is not None:
            # Upstream ended without finish_reason: emit what is still held.
            tail = "".join(sr.flush() for sr in restorers.values())
            if tail:
                for choice in getattr(last, "choices", None) or []:
                    if getattr(choice, "delta", None) is not None:
                        choice.delta.content = tail
                        break
                yield last
