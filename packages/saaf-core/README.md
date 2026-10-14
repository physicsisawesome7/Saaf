# saaf

India-first PII masking and restore for LLM traffic. Zero runtime dependencies. Python 3.11+.

```bash
pip install saaf            # core
pip install "saaf[crypto]"  # encrypted SQLite/Redis vaults
```

```python
from saaf import Saaf, Policy

saaf = Saaf()  # one session per conversation
r = saaf.mask("PAN ABCPE1234F, mobile +91 98765 43210")
r.text  # 'PAN [PAN_1], mobile [PHONE_IN_1]'
r.summary()  # {'entity_counts': {'PAN': 1, 'PHONE_IN': 1}, ...}  (no values)

saaf.restore("Your [pan_1] is linked to PHONE_IN_1.").text

# Streaming
s = saaf.stream_restorer()
for chunk in llm_stream:
    print(s.feed(chunk), end="")
print(s.flush())

# Policy as code
saaf = Saaf(Policy.load("policy.toml"))
```

## CLI

```bash
saaf scan docs/ notes.txt --fail-on-findings     # CI / pre-commit
saaf scan file.txt --json                        # types, offsets, scores (no values)
saaf mask in.txt --vault v.db > masked.txt       # needs SAAF_VAULT_KEY (64 hex chars)
saaf restore reply.txt --vault v.db
saaf validate aadhaar "2345 6789 0124"
saaf entities
saaf audit verify audit.jsonl                    # needs SAAF_AUDIT_KEY
saaf evidence --audit audit.jsonl --policy policy.toml -o evidence.md
```

## Supported entities

Aadhaar (Verhoeff), Aadhaar VID, PAN, GSTIN (check character), IFSC, UPI ID, email, Indian mobile, payment card (Luhn + IIN), bank account*, voter ID*, passport*, driving licence, vehicle registration, TAN*, Udyam, ABHA number* and address, PIN code*, date of birth*, person name (honorific rule), API keys/secrets. (*context-gated: needs a nearby label.)

See the [repository README](https://github.com/physicsisawesome7/Saaf) and [what Saaf doesn't catch](https://github.com/physicsisawesome7/Saaf/blob/main/docs/limitations.md).
