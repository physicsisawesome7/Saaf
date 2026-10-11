#!/usr/bin/env python3
"""Benchmark regression gate.

    python scripts/bench_gate.py BASELINE.json CANDIDATE.json

Fails (exit 1) when Saaf's strict micro-F1 drops by more than 0.005, or its
hard-negative false positives per 1k tokens rise by more than 10% (and by more
than 0.05 absolute, so tiny baselines don't make the gate flaky), or restore
round-trip drops below 0.995. Improvements print a reminder to commit the new
results.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

F1_DROP = 0.005
FP_RISE_REL = 0.10
FP_RISE_ABS = 0.05
RESTORE_MIN = 0.995


def saaf(path: str) -> dict:
    for r in json.loads(Path(path).read_text(encoding="utf-8")):
        if r["system"] == "saaf":
            return r
    raise SystemExit(f"{path}: no 'saaf' row")


def main(base_path: str, cand_path: str) -> int:
    base, cand = saaf(base_path), saaf(cand_path)
    f1_b, f1_c = base["strict"]["MICRO"]["f1"], cand["strict"]["MICRO"]["f1"]
    fp_b, fp_c = base["hard_negative_fp_per_1k_tokens"], cand["hard_negative_fp_per_1k_tokens"]
    rr = cand.get("restore_roundtrip") or 0.0
    print(f"strict micro-F1   {f1_b:.4f} -> {f1_c:.4f}")
    print(f"hard-neg FP/1k    {fp_b:.3f} -> {fp_c:.3f}")
    print(f"restore round-trip {rr:.4f}")
    failures = []
    if f1_c < f1_b - F1_DROP:
        failures.append("micro-F1 regressed")
    if fp_c > fp_b * (1 + FP_RISE_REL) and fp_c - fp_b > FP_RISE_ABS:
        failures.append("hard-negative false positives regressed")
    if rr < RESTORE_MIN:
        failures.append("restore round-trip below bar")
    for name, row in cand["strict"].items():
        old = base["strict"].get(name)
        if name != "MICRO" and old and row["f1"] < old["f1"] - 0.02:
            failures.append(f"{name} F1 {old['f1']:.3f} -> {row['f1']:.3f}")
    if failures:
        print("FAIL:", *failures, sep="\n  ")
        return 1
    if f1_c > f1_b + F1_DROP or fp_c < fp_b * (1 - FP_RISE_REL):
        print("Improved: commit the new bench/results/ in this PR.")
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:3]))
