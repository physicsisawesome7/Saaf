# ADR 0005: Labelled placeholder tokens by default

- Status: accepted
- Date: 2026-10-07

## Context
Models must reason about masked values ("the PAN you gave me") and echo them back so they can be restored.

## Decision
The default token is `[ENTITY_N]`: readable, unambiguous to restore, and stable within a session. Format-preserving fakes are opt-in (`token_style = "fake"`), generated so they cannot belong to a real person (an Aadhaar starting with 1; a mobile number starting with 5). Keyed-HMAC tokens are opt-in for cross-session stability.

## Consequences
- Some prompts that validate formats ("is this a valid PAN?") behave differently with labels; fakes cover that case.
- Restore must tolerate how models mangle tokens; the mangling suite in the benchmark tracks this.
