"""Signed, hash-chained audit records.

Records carry entity *types and counts* only -- never raw values, tokens or
offsets that could be joined back to a value. Each record includes the hash of
the previous one and an HMAC-SHA256 signature, so deletion, reordering or
editing of a log is detectable with :func:`verify_chain`.

This is evidence for the operator's own data-protection work. It is not, by
itself, compliance with DPDP or any other law.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

GENESIS = "0" * 64

Sink = Callable[[dict[str, Any]], None]


def _canonical(record: dict[str, Any]) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sign(key: bytes, body: dict[str, Any]) -> str:
    return hmac.new(key, _canonical(body), hashlib.sha256).hexdigest()


class JsonlSink:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def __call__(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class MemorySink(list):  # type: ignore[type-arg]
    def __call__(self, record: dict[str, Any]) -> None:
        self.append(record)


class AuditLogger:
    def __init__(self, sink: Sink, key: bytes, *, tenant: str = "default", prev_hash: str = GENESIS):
        if len(key) < 16:
            raise ValueError("audit signing key must be at least 16 bytes")
        self._sink = sink
        self._key = key
        self.tenant = tenant
        self._prev = prev_hash
        self._lock = threading.Lock()

    def record(
        self,
        event: str,
        *,
        tenant: str | None = None,
        entities: Iterable[str] = (),
        actions: Iterable[str] = (),
        mode: str = "enforce",
        policy: str | None = None,
        destination: str | None = None,
        blocked: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            body: dict[str, Any] = {
                "id": str(uuid.uuid4()),
                "ts": round(time.time(), 3),
                "event": event,
                "tenant": tenant or self.tenant,
                "mode": mode,
                "policy": policy,
                "destination": destination,
                "entity_counts": dict(sorted(Counter(entities).items())),
                "action_counts": dict(sorted(Counter(actions).items())),
                "blocked": blocked,
                "prev": self._prev,
            }
            if extra:
                body["extra"] = extra
            body["sig"] = _sign(self._key, body)
            self._prev = hashlib.sha256(_canonical(body)).hexdigest()
            self._sink(body)
            return body


def verify_chain(records: Iterable[dict[str, Any]], key: bytes, *, start: str = GENESIS) -> tuple[bool, str]:
    """Return ``(ok, message)``. Checks every signature and the hash chain."""
    prev = start
    n = 0
    for n, rec in enumerate(records, 1):
        body = {k: v for k, v in rec.items() if k != "sig"}
        if not hmac.compare_digest(_sign(key, body), str(rec.get("sig", ""))):
            return False, f"record {n}: bad signature"
        if rec.get("prev") != prev:
            return False, f"record {n}: chain broken (record missing, reordered or edited)"
        prev = hashlib.sha256(_canonical(rec)).hexdigest()
    return True, f"{n} records verified"


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
