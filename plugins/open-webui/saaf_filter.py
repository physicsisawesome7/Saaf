"""
title: Saaf PII Filter
author: Saaf contributors
description: Masks Indian PII (Aadhaar, PAN, GSTIN, UPI, mobile, ...) before messages reach the model and restores it in replies.
version: 0.1.0
license: Apache-2.0
requirements: saaf
"""

# Open WebUI filter function. Paste this file into Admin Panel -> Functions,
# or install it from the community site. Open WebUI calls ``inlet`` before
# the model and ``outlet`` after it, per chat.

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from pydantic import BaseModel, Field

from saaf import Policy, Saaf
from saaf.policy import EntityPolicy


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="Filter order; lower runs first.")
        mode: str = Field(default="enforce", description="'enforce' masks; 'shadow' only observes.")
        block_entities: str = Field(
            default="", description="Comma-separated entity ids that block the message, e.g. AADHAAR,PAN."
        )
        allow_entities: str = Field(default="", description="Comma-separated entity ids never masked, e.g. IFSC.")
        threshold: float = Field(default=0.5, description="Minimum detection score.")

    MAX_CHATS = 2_000

    def __init__(self) -> None:
        self.valves = self.Valves()
        self._sessions: OrderedDict[str, Saaf] = OrderedDict()
        self._policy_key: tuple[Any, ...] | None = None

    def _policy(self) -> Policy:
        def ids(s: str) -> list[str]:
            return [x.strip().upper() for x in s.split(",") if x.strip()]

        entities = {e: EntityPolicy(action="block") for e in ids(self.valves.block_entities)}
        entities.update({e: EntityPolicy(action="allow") for e in ids(self.valves.allow_entities)})
        return Policy(mode=self.valves.mode, threshold=self.valves.threshold, entities=entities)  # type: ignore[arg-type]

    def _session(self, body: dict[str, Any]) -> Saaf:
        key_parts = (self.valves.mode, self.valves.block_entities, self.valves.allow_entities, self.valves.threshold)
        if key_parts != self._policy_key:  # valves changed: start fresh
            self._sessions.clear()
            self._policy_key = key_parts
        chat = str(body.get("chat_id") or (body.get("metadata") or {}).get("chat_id") or "default")
        if chat not in self._sessions:
            self._sessions[chat] = Saaf(self._policy())
            while len(self._sessions) > self.MAX_CHATS:
                self._sessions.popitem(last=False)
        self._sessions.move_to_end(chat)
        return self._sessions[chat]

    def inlet(self, body: dict[str, Any], __user__: dict[str, Any] | None = None) -> dict[str, Any]:
        saaf = self._session(body)
        messages, results = saaf.mask_messages(body.get("messages") or [])
        if any(r.blocked for r in results):
            blocked = sorted({a.finding.entity for r in results for a in r.applied if a.action == "block"})
            raise Exception(f"Message blocked: it contains {', '.join(blocked)}. Remove it and try again.")
        body["messages"] = messages
        return body

    def outlet(self, body: dict[str, Any], __user__: dict[str, Any] | None = None) -> dict[str, Any]:
        saaf = self._session(body)
        for m in body.get("messages") or []:
            if m.get("role") == "assistant" and isinstance(m.get("content"), str):
                m["content"] = saaf.restore(m["content"]).text
        return body
