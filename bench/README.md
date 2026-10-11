# IndicPII-Bench

An open benchmark for Indian PII detection and restore: per-entity P/R/F1 (strict and relaxed), **false positives on hard negatives**, restore round-trip under token mangling, and latency.

```bash
pip install -e bench            # or: uv sync --all-packages
python -m indicpii_bench generate --n 420 --seed 7 -o corpus/v0/docs.jsonl
python -m indicpii_bench run --corpus corpus/v0/docs.jsonl --systems saaf,regex-baseline,presidio
```

- `corpus/v0/`: synthetic, deterministic (seed 7). All identifiers are invented.
- `corpus/handwritten/`, `corpus/community/`: human-written samples (Phase 0/2).
- `corpus/heldout/`: **private**, never committed (in `.gitignore`).
- `results/`: the latest committed run; CI fails on regressions (`scripts/bench_gate.py`).

Methodology and fairness rules: [docs/benchmark.md](../docs/benchmark.md).
