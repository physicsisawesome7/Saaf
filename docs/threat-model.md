# Threat model (v1, draft for P0-4 review)

Method: STRIDE over the assets and trust boundaries below. Review at every phase gate.

## Assets

1. **Raw personal data** in prompts, documents and replies.
2. **The vault mapping** from token to original. It turns pseudonymised text back into personal data.
3. **Vault and audit keys.**
4. **Audit log integrity**, which is the evidence customers rely on.
5. **Policy** that decides what is masked, blocked or allowed.

## Trust boundaries

- Application ↔ Saaf (library in-process; gateway over the local network)
- Saaf ↔ LLM provider (untrusted for raw PII by assumption)
- Saaf ↔ vault backend (SQLite file, Redis)
- Browser page ↔ extension content script (hostile page JavaScript)
- Console users ↔ console (Phase 3+)

## Threats and mitigations

| # | Threat | STRIDE | Mitigation | Status |
|---|---|---|---|---|
| T1 | PII slips past detection (novel format, names, images) | I | Benchmark + held-out split, shadow-mode reports, `docs/limitations.md`, NER (P3-04) | partial; inherent limit |
| T2 | Evasion: zero-width characters, homoglyphs, Indic digits, spacing | I | Normalization with offset map; evasion slice (P3-06) | done for listed cases |
| T3 | Split identifiers across turns | I | `CrossTurnTracker`; prior-turn leaks reported, since they cannot be recalled | P1 basic |
| T4 | Vault theft | I | In memory by default; AES-GCM; HMAC lookups; TTL; crypto-shredding; KMS (P4-02) | done (v0) |
| T5 | Token-guessing on hmac/hash tokens: an attacker with outputs tests candidate Aadhaar numbers | I | Keyed HMAC (secret per tenant), never a bare hash; key in KMS | done |
| T6 | Raw values in logs, errors, metrics, audit | I | `to_dict()` omits values by default; audit stores counts; tests assert absence | done; extend to gateway logs (P2-01) |
| T7 | Cross-tenant token leak through gateway session reuse | I | New `Saaf` per request; tenant-scoped vault namespaces and AAD | done |
| T8 | Tenant header path traversal into policy files | T/E | Tenant name allow-list regex; 400 otherwise | done |
| T9 | Model emits a fabricated token to extract another value | I/S | Tokens resolve only within the issuing session; `on_unknown_token` | done |
| T10 | Audit tampering (delete, reorder, edit) | T/R | HMAC signatures + hash chain; `saaf audit verify`; Ed25519 + external anchoring (P4-03) | v0 done |
| T11 | Hostile page JavaScript reads the masked/unmasked draft in the extension | I | Out of scope: the page already has the draft. The extension never sends data anywhere and keeps only aggregate counts | accepted |
| T12 | Extension selector config tampering (P3-01 remote config) | T | Signed config, pinned public key in the extension | planned |
| T13 | Supply-chain compromise of releases | T | Trusted Publishing, attestations, npm provenance, cosign, SBOM, pinned Actions, 2FA | configured |
| T14 | Denial of service through huge prompts / regex backtracking | D | Linear-time patterns (no nested quantifiers on overlapping classes), request size limits (P2-01), fuzzing | review in P1 |
| T15 | Policy misconfiguration (allow everything) | E | Policy validation, fingerprint in audit, console diff + review (P3-02) | partial |
| T16 | Upstream header leakage (cookies, internal auth) | I | Fixed allow-list of forwarded headers | done |

## Out of scope

- Compromised application host: whoever controls the process sees plaintext.
- What the LLM provider does with masked text.
- Legal sufficiency for DPDP or any other regime.
