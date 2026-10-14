<p align="center"><img src="apps/website/assets/brand/saaf-lockup.svg" alt="Saaf by Safearly" width="320"></p>

# Saaf by Safearly

**India-first PII masking and restore for LLM traffic.** Saaf finds Aadhaar, PAN, GSTIN, UPI IDs, Indian mobile numbers, bank and card numbers, ABHA and more in prompts. It validates them with checksums, so order IDs aren't mistaken for Aadhaar numbers. It swaps them for tokens before the text reaches a model, and puts the real values back in the reply, including streamed replies.

> **Clean prompts. Caught early.** Website: [safearly.com](https://safearly.com)
>
> **Try it now:** [safearly.com/playground](https://safearly.com/playground) — chat with a real model through Saaf, or mask a CSV, right in your browser. Running it yourself: [docs/try-it.md](docs/try-it.md).

```python
from saaf import Saaf

saaf = Saaf()
masked = saaf.mask("Mera aadhar 2345 6789 0124 hai, PAN abcpe1234f. Order ID 234567890124.")
masked.text
# 'Mera aadhar [AADHAAR_1] hai, PAN [PAN_1]. Order ID 234567890124.'
# (the order ID passes the Aadhaar checksum, but the "Order ID" label keeps it unmasked)

saaf.restore("Verified [aadhaar_1] and PAN_1's record.").text
# 'Verified 2345 6789 0124 and abcpe1234f's record.'
```

## Why Saaf

- **Validation, not just patterns.** Verhoeff for Aadhaar, Luhn + IIN for cards, PAN holder-type checks, GSTIN check characters, IFSC/UPI/state-code rules.
- **Messy real-world text.** Hinglish and Hindi context ("aadhar", "adhaar", "आधार"), Devanagari and other Indic digits, zero-width characters, homoglyphs, spaced or hyphenated groupings, and **checksum-assisted OCR repair** (`2345 67B9 O124` is still an Aadhaar).
- **Hard negatives are handled.** The nearest label wins, so `Order ID`, `ref`, `txn`, `AWB` and `UTR` suppress look-alikes without hiding real IDs on the next line.
- **Restore that survives models.** Tolerant to case, dropped brackets, markdown escaping, possessives and JSON tool-call arguments, and streaming-safe across chunk boundaries.
- **Evidence, not claims.** Policy-as-code, shadow mode, signed and hash-chained audit records with types and counts only, and an evidence-pack generator.
- **Measured in public.** [IndicPII-Bench](bench/) reports per-entity scores and false positives on hard negatives.

| IndicPII-Bench v1 (2,500 docs) | Strict micro-F1 | Look-alike false alarms / 1k tokens | ms per KB | Installed size |
|---|---|---|---|---|
| Saaf | 0.711 | 0.35 | 0.94 | 0.1 MB |
| Presidio 2.2, India recognizers on, threshold tuned | 0.437 | 131.34 | 41.4 | 691 MB |
| Bare-regex baseline | 0.466 | 245.66 | 0.15 | — |

Both tools score near zero on unlabelled Indian names, and Saaf's identifier rules were tuned on the same synthetic families, so read its scores as optimistic until the human-labelled gold set lands. Details and caveats: [bench/results/v1](bench/results/v1/README.md), [docs/benchmark.md](docs/benchmark.md).

## Packages

> Not on PyPI or npm yet. Until the first release, install from GitHub, for example `pip install "saaf @ git+https://github.com/physicsisawesome7/Saaf#subdirectory=packages/saaf-core"`, or follow [docs/try-it.md](docs/try-it.md).

| Path | What | Install |
|---|---|---|
| [`packages/saaf-core`](packages/saaf-core) | Python library + `saaf` CLI, zero dependencies | `pip install saaf` |
| [`packages/saaf-js`](packages/saaf-js) | TypeScript port for Node and the browser | `npm i @safearly/saaf` |
| [`packages/saaf-gateway`](packages/saaf-gateway) | OpenAI- and Anthropic-compatible masking proxy | `pip install saaf-gateway` / Docker |
| [`plugins/litellm`](plugins/litellm) | LiteLLM proxy guardrail | `pip install saaf-litellm` |
| [`plugins/open-webui`](plugins/open-webui) | Open WebUI filter function | paste one file |
| [`plugins/langchain`](plugins/langchain) | LangChain wrapper + RAG document masking | `pip install saaf-langchain` |
| [`plugins/mcp-server`](plugins/mcp-server) | MCP tools for Claude and other clients | `pip install saaf-mcp` |
| [`plugins/claude-code-hook`](plugins/claude-code-hook) | Blocks prompts and file writes containing PII | one script |
| [`plugins/browser-extension`](plugins/browser-extension) | Warns and masks before you send to ChatGPT / Claude / Gemini | load unpacked (store listing in Phase 3) |
| [`plugins/n8n-node`](plugins/n8n-node) | n8n community node (scaffold) | — |
| [`apps/website`](apps/website) | safearly.com: single page with the live in-browser demo, plus brand assets | static site |
| [`bench`](bench) | IndicPII-Bench generator, harness, corpus | `pip install -e bench` |

## Quick starts

**Gateway:** point your SDK at it and nothing else changes.
```bash
pip install saaf-gateway
saaf-gateway --port 8787
```
```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8787/v1")  # masked on the way out, restored on the way back
```

**CLI and pre-commit:** stop PII from being committed.
```bash
saaf scan notes.txt --fail-on-findings
```
```yaml
# .pre-commit-config.yaml
- repo: https://github.com/physicsisawesome7/Saaf
  rev: core-v0.1.0
  hooks: [{ id: saaf-scan }]
```

**Policy:** start in shadow mode, then enforce. See [docs/policy.md](docs/policy.md).
```toml
[policy]
mode = "shadow"
[entities.SECRET]
action = "block"
```

## Limits

Saaf reduces exposure; it does not guarantee anonymity or legal compliance. It does **not** reliably catch names without an honorific, free-text addresses, images, or unlabeled generic numbers (bank accounts, PIN codes). Restore depends on the model echoing tokens recognisably. Read **[What Saaf doesn't catch](docs/limitations.md)**.

Saaf produces evidence and safeguards to support your own DPDP work; it is not a compliance certification.

## Development

```bash
make setup     # uv sync + npm install + pre-commit
make test      # Python + TypeScript + conformance + spec drift
make bench     # regenerate corpus v0 and run IndicPII-Bench
```

The roadmap, phase gates and engineering process are in **[docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)**. Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md), and never put real personal data in issues, tests or fixtures.

## License

[Apache-2.0](LICENSE)
