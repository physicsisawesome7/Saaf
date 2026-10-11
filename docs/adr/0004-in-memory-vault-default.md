# ADR 0004: In-memory vault by default; persistent vaults must be encrypted

- Status: accepted
- Date: 2026-10-07

## Context
Pseudonymised data is still personal data while the token mapping exists. A persistent vault is a concentrated PII store.

## Decision
`Saaf()` uses `InMemoryVault`. `SQLiteVault`/`RedisVault` require a key provider (AES-GCM, with HMAC lookups instead of plaintext indexes) and refuse plaintext unless `allow_plaintext=True` is passed explicitly. TTLs default to one hour for persistent backends. Destroying a tenant key crypto-shreds its entries.

## Consequences
- Restore across process restarts requires deliberate configuration.
- An external review of the vault cryptography is a prerequisite for enterprise sales (P4-04).
