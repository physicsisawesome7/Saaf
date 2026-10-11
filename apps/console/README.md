# Console (Phase 3, P3-02: not started)

Scope from the plan:
- Policy editor (TOML with validation, diff and review)
- Shadow-mode detection feed (types and counts only)
- False-positive triage that exports synthetic conformance vectors
- Audit log viewer, chain verification, evidence-pack export
- Vault TTL controls; team access (SSO/RBAC in Phase 4)

Data sources: gateway audit JSONL / OpenTelemetry events and the gateway admin API (to be designed in P2-01/P3-02). The console never receives raw values.

Enterprise features in the console are part of the commercial tier (ADR 0003).
