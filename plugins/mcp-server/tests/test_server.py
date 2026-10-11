from __future__ import annotations

import pytest

pytest.importorskip("mcp")

from saaf_mcp.server import saaf_entities, saaf_mask, saaf_restore, saaf_scan

PAN = "ABCPE1234F"


def test_scan_hides_values() -> None:
    out = saaf_scan(f"PAN {PAN}")
    assert out["count"] == 1
    assert PAN not in str(out)


def test_mask_restore_sessions() -> None:
    masked = saaf_mask(f"PAN {PAN}", session="s1")["text"]
    assert masked == "PAN [PAN_1]"
    assert saaf_restore("x [PAN_1]", session="s1")["text"] == f"x {PAN}"
    assert saaf_restore("x [PAN_1]", session="s2")["text"] == "x [PAN_1]"


def test_entities() -> None:
    assert any(e["id"] == "AADHAAR" for e in saaf_entities())
