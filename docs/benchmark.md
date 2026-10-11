# IndicPII-Bench methodology

Whoever defines the evaluation gets cited. That only holds if the benchmark is fair, reproducible and hard to overfit.

## Corpus

| Split | Content | Where |
|---|---|---|
| `synthetic/v0` | 420 documents from 6 templates (KYC, bank statement, Hinglish chat, support ticket, OCR scan, invoice) plus hard negatives. All identifiers are invented and checksum-valid. | `bench/corpus/v0/docs.jsonl` (seed 7) |
| `handwritten/v0` | ≥ 50 messy samples written by people (P0-6) | `bench/corpus/handwritten/` |
| `community` | Reviewed contributions (synthetic only) | `bench/corpus/community/` |
| `heldout` | Private split, rotated every release, **never committed** | encrypted bucket |

Document format (JSONL): `{"id", "domain", "text", "spans": [{"start", "end", "entity"}], "hard_negative": bool, "noise": [...]}`.

## Metrics

- **Per-entity precision, recall and F1**, strict (exact span and type) and relaxed (overlapping span, same type). Micro-averaged totals.
- **False positives per 1,000 whitespace tokens on hard-negative documents** (order IDs, AWB, UTR, invoice and transaction numbers). This is the headline number.
- **Restore round-trip accuracy** after mangling tokens the way models do: lowercase, dropped brackets, possessives, markdown escaping, spaces for underscores, JSON quoting.
- **Latency** p50/p99 per document, plus install size and cold start (P1-12).
- **Streaming correctness**: covered by property tests rather than the corpus.

## Systems compared

Saaf, a bare-regex baseline, Presidio with India recognizers, LLM Guard, Armos, pygovernor (svitch), bharat-pii, and a managed service as a reference point. Adapters map each tool's labels onto Saaf's entity ids. Labels a tool does not support count as misses for that entity; the per-entity table makes that visible.

## Reproduce

```bash
cd bench
python -m indicpii_bench generate --n 420 --seed 7 -o corpus/v0/docs.jsonl
python -m indicpii_bench run --corpus corpus/v0/docs.jsonl --systems saaf,regex-baseline,presidio
```

## Current results (synthetic v0: a smoke test, not a claim)

See [`bench/results/results.md`](../bench/results/results.md). Publish claims only from runs that include the hand-written and held-out splits.

## Rules for fairness

- Run competitors with their documented defaults, and also tuned if their docs describe tuning. Report both.
- Publish adapter code and versions. Invite maintainers to correct adapters before publishing.
- Never tune Saaf on the held-out split. Rotate it whenever its contents might have leaked.
