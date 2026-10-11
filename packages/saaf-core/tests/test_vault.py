from __future__ import annotations

import fnmatch
import sqlite3
import time

import pytest
from conftest import PAN

from saaf import InMemoryVault, Policy, RedisVault, Saaf, SQLiteVault, StaticKeyProvider
from saaf.vault import VaultError

pytest.importorskip("cryptography")
from cryptography.exceptions import InvalidTag


def test_in_memory_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    v = InMemoryVault(ttl=10)
    v.store("[PAN_1]", "PAN", PAN, PAN)
    assert v.resolve("[PAN_1]") == PAN
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 11)
    assert v.resolve("[PAN_1]") is None
    assert v.lookup("PAN", PAN) is None


def test_sqlite_requires_key(tmp_path) -> None:
    with pytest.raises(VaultError):
        SQLiteVault(tmp_path / "v.db")


def test_sqlite_encrypted_at_rest(tmp_path) -> None:
    keys = StaticKeyProvider.generate("acme")
    path = tmp_path / "v.db"
    vault = SQLiteVault(path, tenant="acme", keys=keys)
    saaf = Saaf(vault=vault)
    masked = saaf.mask(f"PAN {PAN}").text
    vault.close()

    raw = path.read_bytes()
    assert PAN.encode() not in raw

    reopened = Saaf(vault=SQLiteVault(path, tenant="acme", keys=keys))
    assert reopened.restore(masked).text == f"PAN {PAN}"
    assert reopened.mask(f"again {PAN}").text == "again [PAN_1]"  # dedup via HMAC lookup


def test_crypto_shredding(tmp_path) -> None:
    keys = StaticKeyProvider.generate("acme")
    path = tmp_path / "v.db"
    vault = SQLiteVault(path, tenant="acme", keys=keys)
    vault.store("[PAN_1]", "PAN", PAN, PAN)
    vault.close()
    keys.destroy("acme")
    with pytest.raises(VaultError):
        SQLiteVault(path, tenant="acme", keys=keys)
    # Even with a fresh key the ciphertext is unreadable.
    fresh = StaticKeyProvider.generate("acme")
    with pytest.raises(InvalidTag):
        SQLiteVault(path, tenant="acme", keys=fresh).resolve("[PAN_1]")


def test_sqlite_tenants_isolated(tmp_path) -> None:
    keys = StaticKeyProvider.generate("a", "b")
    path = tmp_path / "v.db"
    SQLiteVault(path, tenant="a", keys=keys).store("[PAN_1]", "PAN", PAN, PAN)
    assert SQLiteVault(path, tenant="b", keys=keys).resolve("[PAN_1]") is None


def test_sqlite_purge(tmp_path) -> None:
    vault = SQLiteVault(tmp_path / "v.db", allow_plaintext=True, ttl=0.0001)
    vault.store("[PAN_1]", "PAN", PAN, PAN)
    time.sleep(0.01)
    assert vault.resolve("[PAN_1]") is None
    assert vault.purge_expired() == 1
    with sqlite3.connect(tmp_path / "v.db") as db:
        assert db.execute("select count(*) from saaf_tokens").fetchone()[0] == 0


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.ex: dict[str, int | None] = {}

    def get(self, name):
        return self.data.get(name)

    def set(self, name, value, ex=None):
        self.data[name] = value
        self.ex[name] = ex

    def incr(self, name):
        self.data[name] = int(self.data.get(name, 0)) + 1  # type: ignore[arg-type]
        return self.data[name]

    def scan_iter(self, match):
        return [k for k in list(self.data) if fnmatch.fnmatch(k, match)]

    def delete(self, *names):
        for n in names:
            self.data.pop(n, None)


def test_redis_vault_round_trip() -> None:
    r = FakeRedis()
    keys = StaticKeyProvider.generate("t")
    saaf = Saaf(Policy(), vault=RedisVault(r, tenant="t", keys=keys, ttl=60))
    masked = saaf.mask(f"PAN {PAN}").text
    assert all(PAN.encode() not in v for v in r.data.values() if isinstance(v, bytes))
    assert set(r.ex.values()) == {60}
    assert saaf.restore(masked).text == f"PAN {PAN}"
    saaf.vault.clear()
    assert r.data == {}
