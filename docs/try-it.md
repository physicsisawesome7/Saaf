# Try Saaf

There are three ways to try Saaf, from zero setup to production shape. Use made-up values, never real ones. The samples in the playground are synthetic but pass the real checksums.

| | Setup | What you see |
|---|---|---|
| [1. Browser playground](#1-browser-playground) | none | Chat with a real model through Saaf; mask and restore whole files |
| [2. Python or the CLI](#2-python-or-the-cli) | `pip install` from GitHub | The library in your own code and scripts |
| [3. Gateway](#3-gateway) | Docker or Python | The production setup: an OpenAI/Anthropic-compatible proxy your apps point at |

## 1. Browser playground

Open **https://safearly.com/playground**.

- **Chat with a model.** Pick the simulated model (no key needed) or bring your own OpenAI, Anthropic, Gemini or OpenRouter key, or a local Ollama. Your message is masked in the tab before it is sent. Switch *View as → The model* to see exactly what the model received and wrote. Real values never reached it.
- **Why it was caught.** For each detection you see the type, score and evidence: checksum passed, label nearby, OCR-repaired, or spelled-out digits.
- **Policy.** Switch to shadow mode, raise the threshold, or set any type to block, warn or allow. Blocked messages never leave the tab.
- **Mask a file.** Drop a CSV, JSON, JSONL, text or log file (up to 25 MB). For CSV/TSV, each column header is used as context, so a checksum-valid 12-digit number under `order_id` stays and one under `aadhaar` is masked. Download the masked file and the vault. Later, restore any file that has placeholders in it.
- **Evidence log.** Download a JSON record of what left the tab: masked text, types and counts, never the real values.

Keys are held in memory only and sent straight from your browser to the provider you picked. The page loads no third-party code, and its Content-Security-Policy only allows those provider hosts and `localhost`.

**Local models.** Start Ollama so the page may call it:

```bash
OLLAMA_ORIGINS=https://safearly.com ollama serve
```

On Windows PowerShell: `$env:OLLAMA_ORIGINS="https://safearly.com"; ollama serve`. Chrome may ask to let the site reach devices on your local network: allow it.

## 2. Python or the CLI

Until the first release is on PyPI, install from GitHub (Python 3.11+):

```bash
pip install "saaf @ git+https://github.com/physicsisawesome7/Saaf#subdirectory=packages/saaf-core"
```

```bash
echo "mera aadhaar 2345 6789 0124 hai, PAN ABCPE1234F" | saaf mask
```

```bash
saaf scan --json customers.csv
```

```python
from saaf import Saaf

s = Saaf()
masked = s.mask("Aadhaar 2345 6789 0124, call +91 98765 43210")
print(masked.text)  # Aadhaar [AADHAAR_1], call [PHONE_IN_1]
reply = "Verified [aadhaar_1]; will call \\[PHONE_IN_1\\]."  # models mangle tokens
print(s.restore(reply).text)  # Verified 2345 6789 0124; will call +91 98765 43210.
```

See [`examples/python/quickstart.py`](../examples/python/quickstart.py) for a full model call with streaming restore.

## 3. Gateway

The gateway is the production setup. Apps point their OpenAI or Anthropic SDK at it, and it masks requests, calls the provider and restores replies, including streams. The provider only ever sees placeholders.

**With Docker**, from a clone of the repository:

```bash
docker compose -f examples/demo/docker-compose.yml up --build
```

**Without Docker** (Python 3.11+), no clone needed:

```bash
pip install "saaf[crypto] @ git+https://github.com/physicsisawesome7/Saaf#subdirectory=packages/saaf-core" "saaf-gateway @ git+https://github.com/physicsisawesome7/Saaf#subdirectory=packages/saaf-gateway"
```

or, from a clone: `pip install -e "packages/saaf-core[crypto]" -e packages/saaf-gateway`.

```bash
SAAF_CORS_ORIGINS=https://safearly.com saaf-gateway --port 8787
```

Then either:

- in the playground pick **Saaf gateway on this computer** and paste your OpenAI key (it is passed through), or
- point any OpenAI client at it:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8787/v1")
r = client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[{"role": "user", "content": "Summarise: PAN ABCPE1234F, mobile 9876543210"}],
)
print(r.choices[0].message.content)  # real values, restored by the gateway
```

Every response carries `x-saaf-entities` (for example `PAN=1,PHONE_IN=1`), so you can confirm what was masked. To run fully offline against Ollama, set `SAAF_UPSTREAM_OPENAI=http://localhost:11434` (or `http://host.docker.internal:11434` with Docker).

Policies live in [`examples/policies`](../examples/policies): `default.toml` masks, `shadow.toml` only reports, `strict.toml` blocks high-severity identifiers. See [policy.md](policy.md).

## What to expect

Saaf is strong on structured Indian identifiers (Aadhaar, PAN, GSTIN, UPI, IFSC, mobile, bank accounts with a label) and on look-alikes it should leave alone. It is weak on names without a label or honorific, free-text addresses and unlabelled numbers: see [limitations.md](limitations.md) and the [benchmark](../bench/results/v1/README.md). If it gets something wrong, the playground's **Report a wrong detection** button prepares an issue with masked text only.
