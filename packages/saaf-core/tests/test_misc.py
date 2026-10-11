"""Normalization, audit chain, evidence, spec sync and CLI."""

from __future__ import annotations

import json
import os
from importlib import resources

import pytest
from conftest import AADHAAR, PAN, SPEC_DIR

from saaf import AuditLogger, Detector, MemorySink, Policy, verify_chain
from saaf.cli import main
from saaf.evidence import build_evidence
from saaf.normalize import normalize


def test_normalize_offsets_round_trip() -> None:
    text = "PAN​ АВСРЕ１２３４F!"
    n = normalize(text)
    assert n.text == "PAN ABCPE1234F!"
    s = n.text.index("ABCPE")
    os_, oe = n.to_original(s, s + 10)
    assert text[os_:oe] == "АВСРЕ１２３４F"


def test_normalize_indic_digits_and_dashes() -> None:
    assert normalize("২৩৪৫–৬৭৮৯").text == "2345-6789"  # Bengali digits, en dash


def test_bundled_spec_matches_canonical() -> None:
    bundled = json.loads(resources.files("saaf").joinpath("_data/entities.json").read_text(encoding="utf-8"))
    canonical = json.loads((SPEC_DIR / "entities.json").read_text(encoding="utf-8"))
    assert bundled == canonical, "run `python scripts/sync_spec.py`"


def test_scan_all_exposes_dropped_candidates() -> None:
    d = Detector()
    all_ = d.scan_all("order 234567890124")
    assert any(f.entity == "AADHAAR" and f.score < 0.5 for f in all_)
    assert d.scan("order 234567890124") == []


def test_finding_to_dict_hides_text() -> None:
    f = Detector().scan(f"PAN {PAN}")[0]
    assert "text" not in f.to_dict() and f.to_dict(include_text=True)["text"] == PAN


def test_audit_chain_detects_tampering() -> None:
    key = os.urandom(32)
    sink = MemorySink()
    log = AuditLogger(sink, key)
    for _ in range(3):
        log.record("mask", entities=["PAN"], actions=["mask"])
    assert verify_chain(sink, key)[0]
    assert not verify_chain([sink[0], sink[2]], key)[0]  # deletion
    edited = [dict(r) for r in sink]
    edited[1]["entity_counts"] = {}
    assert not verify_chain(edited, key)[0]
    assert not verify_chain(sink, os.urandom(32))[0]


def test_evidence_pack() -> None:
    key = os.urandom(32)
    sink = MemorySink()
    AuditLogger(sink, key).record("mask", entities=["PAN", "PAN"], actions=["mask"], destination="api.x")
    md = build_evidence(Policy(), list(sink), audit_key=key, processors=["Example LLM Inc."])
    assert "PASS" in md and "| PAN | 2 |" in md and "Example LLM Inc." in md
    assert "not a statement of legal compliance" in md


def test_cli_scan(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "a.txt"
    f.write_text(f"line one\naadhaar {AADHAAR}\n", encoding="utf-8")
    assert main(["scan", str(f)]) == 0
    out = capsys.readouterr().out
    assert ":2:9: AADHAAR" in out and AADHAAR not in out
    assert main(["scan", str(f), "--fail-on-findings"]) == 1
    capsys.readouterr()
    main(["scan", str(f), "--json", "--show-values"])
    assert json.loads(capsys.readouterr().out)[0]["text"] == AADHAAR


def test_cli_mask_restore_with_encrypted_vault(tmp_path, monkeypatch, capsys) -> None:
    pytest.importorskip("cryptography")
    monkeypatch.setenv("SAAF_VAULT_KEY", os.urandom(32).hex())
    src = tmp_path / "in.txt"
    src.write_text(f"PAN {PAN}", encoding="utf-8")
    vault = str(tmp_path / "v.db")
    assert main(["mask", str(src), "--vault", vault]) == 0
    masked = capsys.readouterr().out
    assert masked == "PAN [PAN_1]"
    out = tmp_path / "out.txt"
    out.write_text("Reply: [PAN_1]", encoding="utf-8")
    assert main(["restore", str(out), "--vault", vault]) == 0
    assert capsys.readouterr().out == f"Reply: {PAN}"


def test_cli_validate_and_entities(capsys) -> None:
    assert main(["validate", "aadhaar", AADHAAR]) == 0
    assert main(["validate", "pan", "ABCXE1234F"]) == 1
    assert main(["entities"]) == 0
    assert "AADHAAR" in capsys.readouterr().out
