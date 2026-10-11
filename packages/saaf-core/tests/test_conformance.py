"""Shared conformance vectors. The TypeScript port runs the same files."""

from __future__ import annotations

import json

import pytest
from conftest import CONFORMANCE, SPEC_DIR, load_jsonl

from saaf import Detector
from saaf.restore import Restorer
from saaf.spec import parse_spec
from saaf.validators import VALIDATORS
from saaf.vault import InMemoryVault


@pytest.mark.parametrize("case", load_jsonl("validators.jsonl"), ids=lambda c: f"{c['validator']}:{c['input']}")
def test_validator_vectors(case: dict) -> None:
    assert VALIDATORS[case["validator"]](case["input"]) is case["expect"]


@pytest.fixture(scope="module")
def detector() -> Detector:
    # Use the canonical spec at the repo root, not the bundled copy.
    spec = parse_spec(json.loads((SPEC_DIR / "entities.json").read_text(encoding="utf-8")))
    return Detector(spec)


@pytest.mark.parametrize("case", load_jsonl("detect.jsonl"), ids=lambda c: c["id"])
def test_detect_vectors(case: dict, detector: Detector) -> None:
    got = [{"entity": f.entity, "text": f.text} for f in detector.scan(case["text"])]
    assert got == case["expect"], case.get("note", "")


@pytest.mark.parametrize("case", load_jsonl("restore.jsonl"), ids=lambda c: c["id"])
def test_restore_vectors(case: dict) -> None:
    vault = InMemoryVault()
    for token, original in case["vault"].items():
        vault.store(token, "X", original, original)
    res = Restorer(vault).restore(case["input"])
    assert res.text == case["expect"]
    assert res.unknown == case.get("unknown", [])


def test_vector_files_exist() -> None:
    assert {p.name for p in CONFORMANCE.glob("*.jsonl")} >= {"validators.jsonl", "detect.jsonl", "restore.jsonl"}
