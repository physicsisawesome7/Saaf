"""Evidence pack: a Markdown summary built from a policy and an audit log.

Describes what the safeguard did; it is input to the operator's own DPDP work,
not a compliance certificate. Have counsel review any external use.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from saaf._version import __version__
from saaf.audit import verify_chain
from saaf.policy import Policy


def build_evidence(
    policy: Policy,
    records: list[dict[str, Any]],
    *,
    audit_key: bytes | None = None,
    processors: Iterable[str] = (),
    vault_backend: str = "in-memory",
    vault_ttl: float | None = None,
) -> str:
    entities: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    destinations: Counter[str] = Counter()
    blocked = 0
    for r in records:
        entities.update(r.get("entity_counts", {}))
        actions.update(r.get("action_counts", {}))
        destinations[r.get("destination") or "(unspecified)"] += 1
        blocked += bool(r.get("blocked"))
    if audit_key is not None:
        ok, msg = verify_chain(records, audit_key)
        integrity = ("PASS: " if ok else "FAIL: ") + msg
    else:
        integrity = "not verified (no key supplied)"
    first = min((r["ts"] for r in records), default=None)
    last = max((r["ts"] for r in records), default=None)

    def ts(t: float | None) -> str:
        return datetime.fromtimestamp(t, UTC).isoformat() if t else "-"

    lines = [
        "# Saaf evidence pack",
        "",
        f"Generated {datetime.now(UTC).isoformat()} by saaf {__version__}.",
        "",
        "> This document describes technical safeguards. It is not a statement of legal compliance.",
        "",
        "## Scope",
        f"- Audit records: {len(records)} ({ts(first)} to {ts(last)})",
        f"- Audit log integrity: {integrity}",
        f"- Policy: `{policy.id}` (fingerprint `{policy.fingerprint}`), mode `{policy.mode}`",
        "",
        "## Data flow",
        "Application -> Saaf (detect, apply policy, tokenize) -> LLM provider -> Saaf (restore) -> Application.",
        "Raw values never leave the Saaf process for masked entity types; only tokens are forwarded.",
        "",
        "### Destinations",
        *[f"- {d}: {n} requests" for d, n in destinations.most_common()],
        "",
        "## Processors",
        *([f"- {p}" for p in processors] or ["- (none declared)"]),
        "",
        "## Detections (types and counts only)",
        "| Entity | Count |",
        "|---|---|",
        *[f"| {e} | {n} |" for e, n in entities.most_common()],
        "",
        "## Actions",
        *[f"- {a}: {n}" for a, n in actions.most_common()],
        f"- requests blocked: {blocked}",
        "",
        "## Retention",
        f"- Vault backend: {vault_backend}",
        f"- Vault TTL: {f'{vault_ttl:.0f} s' if vault_ttl else 'session lifetime (in-memory)'}",
        "- Audit records contain entity types and counts only, never raw values.",
        "",
        "## Policy",
        "```json",
        json.dumps(policy.to_dict(), indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)
