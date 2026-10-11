# Architecture

## Data flow

```
 app / user ──► Saaf (detect → policy → tokenize) ──► LLM provider
                       │  vault: token → original
 app / user ◄── Saaf (tolerant restore, streaming) ◄── model reply
                       │
                       └─► audit record (types and counts only, signed, hash-chained)
```

Every surface (library, gateway, plugins, extension) runs the same pipeline, defined once in `spec/entities.json`.

## Detection pipeline

1. **Normalize** (`normalize.py` / `normalize.ts`). Per code point: drop zero-width characters, fold Indic digits to ASCII, fold Unicode dashes, fold Cyrillic/Greek homoglyphs, then NFKC. An index map keeps every normalized character tied to its original offset, so masking replaces the original span exactly.
2. **Match candidates.** Each entity has one or more regexes. They are written to run unchanged in Python `re` (with `re.ASCII`) and in JavaScript `RegExp`.
3. **Canonicalize** (`digits`, `alnum_upper`, `lower`, `strip`). This is the form fed to validators and used for vault deduplication.
4. **Validate** with a named validator (`verhoeff`, `aadhaar`, `card`, `pan`, `gstin`, `ifsc`, `upi_handle`, `in_mobile`, `in_state_code`, `udyam`). `on_invalid: drop` discards the candidate; `on_invalid: base` keeps it at `base_score`, so it needs context to pass.
5. **Score with context.** Positive keywords are searched in a ±50-character window. Negative keywords ("order", "ref", "txn", …) are searched only within the candidate's own line and sentence. When both are present, the nearer keyword wins. `requires_context` entities (bank account, PIN code, DOB, …) are dropped without a positive keyword.
6. **OCR repair.** For entities with an `ocr` block, a looser regex admits confusable characters (O/0, I/1, S/5, B/8). Each candidate is repaired against a digit/letter shape, and it is kept only if a variant passes the validator.
7. **Threshold and overlap resolution.** Greedy selection by score, then priority, then length.
8. **Map spans** back to the original text.

## Session and tokens

`Saaf` is one conversation's state: policy, detector (stateless and shared) and vault. The same canonical value gets the same token within a session, so the model sees one entity. As a result, restore returns each value's **first-seen spelling**: an Aadhaar written once in ASCII and once in Devanagari digits comes back in ASCII both times. Token styles:

| Style | Example | Restorable | Use |
|---|---|---|---|
| label | `[AADHAAR_1]` | yes | default; readable by models |
| hmac | `[AADHAAR_3fa2b1c9]` | yes (with the vault) | stable across sessions, for example RAG indexing |
| fake | `1834 5521 0937` | yes | format-preserving; a Verhoeff-valid Aadhaar starting with 1 can never be real |
| hash (action) | `[AADHAAR#3fa2b1c9]` | no | irreversible pseudonym |

## Restore

`Restorer` builds one tolerant regex per issued token (case, brackets, spaces for underscores, markdown escapes, possessives; `AADHAAR_1` never matches inside `AADHAAR_10`). Token-shaped strings that were never issued are handled by `on_unknown_token`: `leave`, `strip` or `flag`. `restore_json` parses tool-call arguments, restores the strings inside and re-serialises them, so values are escaped correctly.

`StreamRestorer` holds back the shortest suffix that could still become a token (an unclosed `[`, or a trailing run that prefixes a known token) and emits everything else at once. A property test checks that any chunking produces the same output as restoring the whole reply.

## Vaults

| Backend | Persistence | Encryption | Deduplication lookup | TTL |
|---|---|---|---|---|
| `InMemoryVault` (default) | none | n/a | in memory | optional |
| `SQLiteVault` | file | AES-GCM per value, AAD = tenant + token | HMAC(key, entity + value) | default 1 h |
| `RedisVault` | Redis | AES-GCM | HMAC | Redis expiry |

Persistent backends refuse to start without a key unless `allow_plaintext=True` is passed. Destroying a tenant key crypto-shreds that tenant's entries.

## Gateway

FastAPI app with `/v1/chat/completions` (OpenAI-compatible) and `/v1/messages` (Anthropic). Per request it opens a new `Saaf` session using the tenant's policy (`x-saaf-tenant` header → `<policy_dir>/<tenant>.toml`), masks messages (and `system` for Anthropic), writes an audit record, forwards a fixed allow-list of headers, and restores the reply. Streams are re-encoded event by event, with held-back text flushed on `finish_reason` / `content_block_stop`. A `block` decision returns 403 and never calls the upstream.

## Port parity

| Capability | Python | TypeScript |
|---|---|---|
| Normalize, validators, detection, OCR repair | ✓ | ✓ |
| Policy: thresholds, mask/warn/allow/block, shadow | ✓ | ✓ |
| Rules by destination/role, hash action, hmac/fake tokens | ✓ | Phase 3 |
| Tolerant restore, streaming | ✓ | ✓ |
| Persistent vaults, audit signing, evidence | ✓ | not planned (server-side concerns) |
| Cross-turn detection | ✓ | Phase 3 |

The conformance vectors define parity. Anything not covered by a vector is allowed to differ.

## Why not Rust/WASM?

See [ADR 0002](adr/0002-declarative-detectors.md). A declarative spec plus small, named validators keeps the two ports honest at a fraction of the cost. We will revisit this only if the browser extension proves demand for heavier logic (NER) running client-side.
