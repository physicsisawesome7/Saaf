# IndicPII-Bench v1: first head-to-head (12 Oct 2026)

**Read the caveats before quoting any number.** This is an internal scoreboard, not a public claim (see section 5 of `docs/COMPETITIVE_EDGE_PLAN.md`).

## Setup

- **Corpus:** 2,500 documents in total.
  - `corpus/v1/docs.jsonl`: 900 synthetic documents in 6 slices, committed.
  - `corpus/external/naamapadam_person.jsonl`: 1,200 human-validated Naamapadam test sentences in Hindi, Marathi, Tamil and Telugu (CC0).
  - `corpus/external/hiner_person.jsonl`: 400 HiNER Hindi news sentences (CC BY-SA, evaluation only).
  - Both external slices are generated locally by `python -m indicpii_bench fetch`.
- **Systems:**
  - `saaf`: spec 0.2.0.
  - `regex-baseline`: bare patterns, no checksums.
  - `presidio`: v2.2.364 out of the box, with India recognizers off as shipped, `en_core_web_lg`, score ≥ 0.5.
  - `presidio-tuned`: all six India recognizers on, with the threshold chosen at **0.4**. It was picked by `sweep` on a separate dev corpus (seed 101), not on this one.
  - `presidio+saaf`: Presidio's spaCy NER plus the `saaf-presidio` pack.
- **Hardware:** Windows laptop CPU, Python 3.13, single thread. Latency is per document after a warm-up.

## Headline

| System | Strict micro-F1 | Look-alike false alarms / 1k tokens | ms per KB | Cold start | Install size |
|---|---|---|---|---|---|
| **saaf** | **0.711** | **0.35** | **0.94** | **12 ms** | **0.1 MB, 0 dependencies** |
| presidio-tuned | 0.437 | 131.34 | 41.4 | 1.2 s | 691 MB, 53 packages |
| presidio (default) | 0.145 | 1.74 | 40.9 | 2.9 s | 691 MB |
| presidio + saaf | 0.620 | 2.08 | 41.6 | 1.3 s | 691 MB |
| bare regex | 0.466 | 245.66 | 0.15 | 0 ms | — |

Per entity (strict F1): Saaf scores **1.00 on Aadhaar, PAN, GSTIN, UPI, IFSC, mobile, bank account and email**. Tuned Presidio scores Aadhaar 0.82, PAN 0.89 and mobile 0.60, and has no UPI, IFSC or bank-account type at all (0.00).

## What changed in spec 0.2.0 because of this benchmark

The first run found that Saaf missed:
- Aadhaar written in digit words (19 of 19), dotted (24 of 24) and spaced out digit by digit (21 of 21);
- hyphenated PANs (15 of 15).

It also raised false alarms on NEFT references, 14-digit account numbers (as cards), serial numbers and emails with apostrophes. All of these are fixed, each with a shared conformance vector that both the Python and TypeScript ports pass. The v0 regression gate improved too: F1 0.9672 → 0.9676, look-alike false alarms 0.829 → 0.000.

## Caveats: this is the truth

1. **The rules were fixed against misses found on this same synthetic corpus.** The 1.00 scores on structured IDs are therefore optimistic. The dev corpus uses the same templates, so it isn't independent either. The real test is the human-written gold set (plan weeks 3–4) and a held-out split we don't look at.
2. **Names are unsolved for everyone.** Saaf's PERSON F1 is 0.29 overall, but that comes from the KYC-label rule ("Name:", "नाम:", "mera naam …") on our own templates. On the **independent** Naamapadam and HiNER news slices, Saaf scores about **0.00** and Presidio 0.02–0.05. This is the gap the Indic name model (workstream E2) has to close, and it is the biggest real moat available.
3. **Presidio is English-only by design here.** Its Hindi- and Tamil-script names are out of scope for `en_core_web_lg`. That is a fair reflection of a default deployment, but a Presidio user could add a multilingual spaCy or transformer model. Workstream E1 adds a GLiNER-PII baseline for exactly this reason.
4. **Restore was not compared.** Presidio has no mask-and-restore path in this setup. LiteLLM's `output_parse_pii` and streaming behaviour still need their own harness (workstream E3).
5. **NeMo Guardrails was not run yet.** Its PII rails use Presidio or GLiNER underneath, so its detection would track those rows. Its restore gap is structural: the rails are one-way.

## Reproduce

```bash
cd bench
python -m indicpii_bench fetch                       # licence-cleared downloads -> data/raw, lexicons, external slices
python -m indicpii_bench generate-v1 --per-slice 150 --seed 23 -o corpus/v1/docs.jsonl
python -m indicpii_bench generate-v1 --per-slice 60 --seed 101 -o corpus/external/dev_v1.jsonl
../.venv-bench/Scripts/python -m indicpii_bench sweep --corpus corpus/external/dev_v1.jsonl
../.venv-bench/Scripts/python -m indicpii_bench run --corpus corpus/v1/docs.jsonl \
    --corpus corpus/external/naamapadam_person.jsonl --corpus corpus/external/hiner_person.jsonl \
    --systems saaf,regex-baseline,presidio,presidio-tuned,presidio+saaf --out-dir results/v1
```

Set `PYTHONPATH="../packages/saaf-core/src;../plugins/presidio/src;."` on Windows; use `:` as the separator elsewhere. `.venv-bench` holds `presidio-analyzer`, `presidio-anonymizer` and `en_core_web_lg`.
