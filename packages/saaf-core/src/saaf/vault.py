"""Token vaults: the mapping from tokens back to original values.

The vault is a concentrated store of personal data. Pseudonymized data is still
personal data while the mapping exists, so:

* the default is :class:`InMemoryVault` -- nothing touches disk;
* persistent backends encrypt values with AES-GCM and refuse to run without a
  key unless ``allow_plaintext=True`` is passed explicitly;
* every backend supports a TTL;
* dedup lookups use a keyed HMAC of the value, never the value itself;
* destroying a tenant key (``KeyProvider.destroy``) crypto-shreds every entry
  written under it.

Persistent backends need the ``cryptography`` package (``pip install
saaf[crypto]``).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class VaultEntry:
    token: str
    entity: str
    original: str
    created: float


class VaultError(RuntimeError):
    pass


class Vault(ABC):
    """Abstract vault. Implementations must be safe to call from one thread at a
    time per instance; :class:`InMemoryVault` and :class:`SQLiteVault` lock."""

    ttl: float | None = None

    @abstractmethod
    def lookup(self, entity: str, canonical: str) -> str | None:
        """Token previously issued for this value, if any."""

    @abstractmethod
    def store(self, token: str, entity: str, canonical: str, original: str) -> None: ...

    @abstractmethod
    def resolve(self, token: str) -> str | None:
        """Original value for a token, or None if unknown/expired."""

    @abstractmethod
    def next_index(self, entity: str) -> int:
        """Next counter value for label tokens of ``entity`` (1-based)."""

    @abstractmethod
    def entries(self) -> list[VaultEntry]: ...

    @abstractmethod
    def clear(self) -> None: ...

    def __len__(self) -> int:
        return len(self.entries())

    def _expired(self, created: float, now: float | None = None) -> bool:
        return self.ttl is not None and (now or time.time()) - created > self.ttl


class InMemoryVault(Vault):
    def __init__(self, ttl: float | None = None):
        self.ttl = ttl
        self._lock = threading.RLock()
        self._by_key: dict[tuple[str, str], str] = {}
        self._by_token: dict[str, tuple[VaultEntry, str]] = {}
        self._counters: dict[str, int] = {}

    def lookup(self, entity: str, canonical: str) -> str | None:
        with self._lock:
            token = self._by_key.get((entity, canonical))
            if token is None:
                return None
            entry, _ = self._by_token[token]
            if self._expired(entry.created):
                self._evict(token)
                return None
            return token

    def store(self, token: str, entity: str, canonical: str, original: str) -> None:
        with self._lock:
            self._by_key[(entity, canonical)] = token
            self._by_token[token] = (VaultEntry(token, entity, original, time.time()), canonical)

    def resolve(self, token: str) -> str | None:
        with self._lock:
            item = self._by_token.get(token)
            if item is None:
                return None
            if self._expired(item[0].created):
                self._evict(token)
                return None
            return item[0].original

    def next_index(self, entity: str) -> int:
        with self._lock:
            self._counters[entity] = self._counters.get(entity, 0) + 1
            return self._counters[entity]

    def entries(self) -> list[VaultEntry]:
        with self._lock:
            self.purge_expired()
            return [e for e, _ in self._by_token.values()]

    def purge_expired(self) -> int:
        with self._lock:
            now = time.time()
            dead = [t for t, (e, _) in self._by_token.items() if self._expired(e.created, now)]
            for t in dead:
                self._evict(t)
            return len(dead)

    def clear(self) -> None:
        with self._lock:
            self._by_key.clear()
            self._by_token.clear()
            self._counters.clear()

    def _evict(self, token: str) -> None:
        entry, canonical = self._by_token.pop(token)
        self._by_key.pop((entry.entity, canonical), None)


# --- keys and encryption ---------------------------------------------------


class KeyProvider(Protocol):
    def get(self, tenant: str) -> bytes | None: ...

    def destroy(self, tenant: str) -> None: ...


class StaticKeyProvider:
    """Holds 32-byte keys in memory. Production deployments should back this
    with a KMS; the interface is deliberately two methods wide."""

    def __init__(self, keys: dict[str, bytes] | None = None):
        self._keys = dict(keys or {})
        for tenant, key in self._keys.items():
            _check_key(tenant, key)

    @classmethod
    def generate(cls, *tenants: str) -> StaticKeyProvider:
        return cls({t: os.urandom(32) for t in tenants})

    def get(self, tenant: str) -> bytes | None:
        return self._keys.get(tenant)

    def destroy(self, tenant: str) -> None:
        self._keys.pop(tenant, None)


def _check_key(tenant: str, key: bytes) -> None:
    if len(key) != 32:
        raise VaultError(f"key for tenant {tenant!r} must be 32 bytes, got {len(key)}")


class _Cipher:
    def __init__(self, key: bytes):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:  # pragma: no cover - exercised without extra
            raise VaultError("encrypted vaults need 'cryptography': pip install saaf[crypto]") from exc
        self._aead = AESGCM(key)
        self._mac_key = hmac.new(key, b"saaf-lookup-v1", hashlib.sha256).digest()

    def seal(self, plaintext: str, aad: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, plaintext.encode(), aad)

    def open(self, blob: bytes, aad: bytes) -> str:
        return self._aead.decrypt(blob[:12], blob[12:], aad).decode()

    def lookup_id(self, entity: str, canonical: str) -> str:
        return hmac.new(self._mac_key, f"{entity}\x1f{canonical}".encode(), hashlib.sha256).hexdigest()


class _PlainCipher:
    """Only used with ``allow_plaintext=True`` (tests, local debugging)."""

    def seal(self, plaintext: str, aad: bytes) -> bytes:
        return plaintext.encode()

    def open(self, blob: bytes, aad: bytes) -> str:
        return blob.decode()

    def lookup_id(self, entity: str, canonical: str) -> str:
        return hashlib.sha256(f"{entity}\x1f{canonical}".encode()).hexdigest()


def _cipher_for(keys: KeyProvider | None, tenant: str, allow_plaintext: bool) -> Any:
    if keys is None:
        if not allow_plaintext:
            raise VaultError("persistent vaults must be encrypted: pass keys=..., or allow_plaintext=True")
        return _PlainCipher()
    key = keys.get(tenant)
    if key is None:
        raise VaultError(f"no key for tenant {tenant!r} (destroyed or never created)")
    _check_key(tenant, key)
    return _Cipher(key)


# --- SQLite ----------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS saaf_tokens (
    tenant   TEXT NOT NULL,
    token    TEXT NOT NULL,
    entity   TEXT NOT NULL,
    lookup   TEXT NOT NULL,
    value    BLOB NOT NULL,
    created  REAL NOT NULL,
    PRIMARY KEY (tenant, token)
);
CREATE INDEX IF NOT EXISTS saaf_tokens_lookup ON saaf_tokens (tenant, lookup);
CREATE TABLE IF NOT EXISTS saaf_counters (
    tenant TEXT NOT NULL,
    entity TEXT NOT NULL,
    value  INTEGER NOT NULL,
    PRIMARY KEY (tenant, entity)
);
"""


class SQLiteVault(Vault):
    def __init__(
        self,
        path: str | Path,
        *,
        tenant: str = "default",
        keys: KeyProvider | None = None,
        ttl: float | None = 3600.0,
        allow_plaintext: bool = False,
    ):
        self.ttl = ttl
        self.tenant = tenant
        self._cipher = _cipher_for(keys, tenant, allow_plaintext)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(_SCHEMA)

    def _aad(self, token: str) -> bytes:
        return f"{self.tenant}\x1f{token}".encode()

    def lookup(self, entity: str, canonical: str) -> str | None:
        lid = self._cipher.lookup_id(entity, canonical)
        with self._lock:
            row = self._db.execute(
                "SELECT token, created FROM saaf_tokens WHERE tenant=? AND lookup=?", (self.tenant, lid)
            ).fetchone()
        if row is None or self._expired(row[1]):
            return None
        return str(row[0])

    def store(self, token: str, entity: str, canonical: str, original: str) -> None:
        blob = self._cipher.seal(original, self._aad(token))
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO saaf_tokens VALUES (?,?,?,?,?,?)",
                (self.tenant, token, entity, self._cipher.lookup_id(entity, canonical), blob, time.time()),
            )

    def resolve(self, token: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT value, created FROM saaf_tokens WHERE tenant=? AND token=?", (self.tenant, token)
            ).fetchone()
        if row is None or self._expired(row[1]):
            return None
        return str(self._cipher.open(row[0], self._aad(token)))

    def next_index(self, entity: str) -> int:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO saaf_counters VALUES (?,?,1) ON CONFLICT(tenant, entity) DO UPDATE SET value = value + 1",
                (self.tenant, entity),
            )
            row = self._db.execute(
                "SELECT value FROM saaf_counters WHERE tenant=? AND entity=?", (self.tenant, entity)
            ).fetchone()
        return int(row[0])

    def entries(self) -> list[VaultEntry]:
        with self._lock:
            rows = self._db.execute(
                "SELECT token, entity, value, created FROM saaf_tokens WHERE tenant=?", (self.tenant,)
            ).fetchall()
        return [VaultEntry(t, e, self._cipher.open(v, self._aad(t)), c) for t, e, v, c in rows if not self._expired(c)]

    def purge_expired(self) -> int:
        if self.ttl is None:
            return 0
        with self._lock, self._db:
            cur = self._db.execute(
                "DELETE FROM saaf_tokens WHERE tenant=? AND created < ?", (self.tenant, time.time() - self.ttl)
            )
        return cur.rowcount

    def clear(self) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM saaf_tokens WHERE tenant=?", (self.tenant,))
            self._db.execute("DELETE FROM saaf_counters WHERE tenant=?", (self.tenant,))

    def close(self) -> None:
        self._db.close()


# --- Redis -----------------------------------------------------------------


class RedisLike(Protocol):
    def get(self, name: str) -> Any: ...

    def set(self, name: str, value: Any, ex: int | None = None) -> Any: ...

    def incr(self, name: str) -> int: ...

    def scan_iter(self, match: str) -> Iterator[Any]: ...

    def delete(self, *names: str) -> Any: ...


class RedisVault(Vault):
    """Redis backend. Pass any client with ``get/set/incr/scan_iter/delete``
    (``redis.Redis`` works). TTL is enforced by Redis key expiry."""

    def __init__(
        self,
        client: RedisLike,
        *,
        tenant: str = "default",
        keys: KeyProvider | None = None,
        ttl: float | None = 3600.0,
        allow_plaintext: bool = False,
        prefix: str = "saaf",
    ):
        self.ttl = ttl
        self.tenant = tenant
        self._r = client
        self._cipher = _cipher_for(keys, tenant, allow_plaintext)
        self._ns = f"{prefix}:{tenant}"

    def _ex(self) -> int | None:
        return int(self.ttl) if self.ttl else None

    def lookup(self, entity: str, canonical: str) -> str | None:
        v = self._r.get(f"{self._ns}:lk:{self._cipher.lookup_id(entity, canonical)}")
        return v.decode() if isinstance(v, bytes) else v

    def store(self, token: str, entity: str, canonical: str, original: str) -> None:
        blob = self._cipher.seal(original, f"{self.tenant}\x1f{token}".encode())
        self._r.set(f"{self._ns}:tok:{token}", entity.encode() + b"\x1f" + blob, ex=self._ex())
        self._r.set(f"{self._ns}:lk:{self._cipher.lookup_id(entity, canonical)}", token, ex=self._ex())

    def _read(self, token: str) -> tuple[str, str] | None:
        raw = self._r.get(f"{self._ns}:tok:{token}")
        if raw is None:
            return None
        entity, _, blob = bytes(raw).partition(b"\x1f")
        return entity.decode(), self._cipher.open(blob, f"{self.tenant}\x1f{token}".encode())

    def resolve(self, token: str) -> str | None:
        item = self._read(token)
        return item[1] if item else None

    def next_index(self, entity: str) -> int:
        return int(self._r.incr(f"{self._ns}:ctr:{entity}"))

    def entries(self) -> list[VaultEntry]:
        out = []
        for key in self._r.scan_iter(match=f"{self._ns}:tok:*"):
            k = key.decode() if isinstance(key, bytes) else key
            token = k.split(":tok:", 1)[1]
            item = self._read(token)
            if item:
                out.append(VaultEntry(token, item[0], item[1], 0.0))
        return out

    def clear(self) -> None:
        keys = list(self._r.scan_iter(match=f"{self._ns}:*"))
        if keys:
            self._r.delete(*keys)
