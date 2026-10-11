from __future__ import annotations

from indicpii_bench.adapters import regex_baseline, saaf_adapter
from indicpii_bench.generate import generate
from indicpii_bench.harness import evaluate


def test_generator_is_deterministic_and_spans_are_exact() -> None:
    a, b = generate(40, seed=3), generate(40, seed=3)
    assert a == b
    for doc in a:
        for s in doc["spans"]:
            assert doc["text"][s["start"] : s["end"]].strip() == doc["text"][s["start"] : s["end"]]


def test_gate_metrics_saaf_beats_bare_regex() -> None:
    """Phase 1 gate in miniature: fewer hard-negative FPs and better recall on
    messy text than the bare-regex approach. The real gate compares against the
    best open-source tool on the full corpus plus the private held-out split."""
    docs = generate(140, seed=11)
    saaf = evaluate("saaf", saaf_adapter(), docs, restore=True).summary()
    base = evaluate("regex", regex_baseline(), docs).summary()
    assert saaf["hard_negative_fp_per_1k_tokens"] < base["hard_negative_fp_per_1k_tokens"] / 10
    assert saaf["strict"]["MICRO"]["f1"] > base["strict"]["MICRO"]["f1"]
    assert saaf["restore_roundtrip"] == 1.0
