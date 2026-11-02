"""Append-only, hash-chained audit log.

Each record's hash covers the previous hash and the canonical JSON of the
record, so any edit or deletion breaks the chain from that point on and
``verify`` reports the first bad sequence number. Query text is stored after
PII masking; the trail proves what happened without becoming a PII store.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from sqlalchemy import select

from .store import Store, audit

GENESIS = "0" * 64


def _digest(prev: str, ts: float, actor: str, action: str, payload: str) -> str:
    body = json.dumps([prev, round(ts, 6), actor, action, payload], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, store: Store, tenant: str):
        self.store = store
        self.tenant = tenant
        self._lock = threading.Lock()

    def _last_hash(self) -> str:
        with self.store.engine.connect() as c:
            r = c.execute(
                select(audit.c.hash).where(audit.c.tenant == self.tenant).order_by(audit.c.seq.desc()).limit(1)
            ).first()
        return r.hash if r else GENESIS

    def record(self, actor: str, action: str, **payload: Any) -> str:
        with self._lock:
            prev = self._last_hash()
            ts = time.time()
            p = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
            h = _digest(prev, ts, actor, action, p)
            self.store.insert(
                audit, tenant=self.tenant, ts=ts, actor=actor, action=action, payload=p, prev_hash=prev, hash=h
            )
            return h

    def tail(self, limit: int = 200, action: str | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {"tenant": self.tenant}
        if action:
            where["action"] = action
        rows = self.store.rows(audit, order_by="seq", limit=limit, **where)
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows

    def verify(self) -> dict[str, Any]:
        prev = GENESIS
        n = 0
        with self.store.engine.connect() as c:
            for r in c.execute(select(audit).where(audit.c.tenant == self.tenant).order_by(audit.c.seq)):
                n += 1
                if r.prev_hash != prev or _digest(prev, r.ts, r.actor, r.action, r.payload) != r.hash:
                    return {"ok": False, "records": n, "broken_at": r.seq}
                prev = r.hash
        return {"ok": True, "records": n, "head": prev}
