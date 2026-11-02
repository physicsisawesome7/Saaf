"""Harness memory beyond the documents.

* **User** memory: one person's notes and preferences. Visible to them only.
* **Team** memory: decisions, FAQs, precedents. Proposed by anyone, approved
  by a knowledge manager before anyone else can retrieve it.

Rules: every item carries provenance and inherits the *strictest* access rule
of whatever it was derived from; writes are proposals that pass a PII filter;
reads go through the same access filter as documents; items derived from a
superseded document are flagged for re-validation; people can see, correct
and delete their own memories, and deletion reaches the index and caches
(DPDP erasure).
"""

from __future__ import annotations

import json
import time
from typing import Any

from .access import evaluate, strictest
from .engine import Tenant
from .models import Access, Principal
from .privacy import mask_text
from .store import memories


def propose(
    t: Tenant, p: Principal, text: str, tier: str = "user", provenance: list[str] | None = None
) -> dict[str, Any]:
    if tier not in ("user", "team"):
        raise ValueError("tier must be 'user' or 'team'")
    provenance = provenance or []
    docs = t.store.documents_by_ids(t.id, provenance)
    for did in provenance:
        d = docs.get(did)
        if not d or not evaluate(p, d["access"], d["doc_type"]).allowed:
            raise PermissionError(f"cannot derive a memory from {did}")
    safe, masked = mask_text(text)
    if tier == "user":
        base = strictest([d["access"] for d in docs.values()]) if docs else Access(doc_class="internal")
        base.groups = [f"user:{p.user_id}"]
        access = base
        status = "approved"
    else:
        access = (
            strictest([d["access"] for d in docs.values()])
            if docs
            else Access(doc_class="internal", divisions=p.divisions or ["*"])
        )
        status = "proposed"
    mid = t.store.insert(
        memories,
        tenant=t.id,
        tier=tier,
        owner=p.user_id,
        text=safe,
        provenance=json.dumps(provenance),
        access=json.dumps(access.to_dict()),
        status=status,
        needs_revalidation=False,
        created_at=time.time(),
    )
    t.audit.record(
        p.user_id, "memory_propose", memory_id=mid, tier=tier, provenance=provenance, pii_masked=sorted(masked)
    )
    if status == "approved":
        _index(t, mid)
    return get(t, mid)


def get(t: Tenant, mid: int) -> dict[str, Any]:
    r = t.store.rows(memories, tenant=t.id, id=mid)
    if not r:
        raise KeyError(mid)
    m = r[0]
    return {**m, "provenance": json.loads(m["provenance"] or "[]"), "access": json.loads(m["access"])}


def _index(t: Tenant, mid: int) -> None:
    m = get(t, mid)
    body = (
        "---\n"
        + json.dumps(
            {
                "title": f"{'Team' if m['tier'] == 'team' else 'Personal'} note #{mid}",
                "doc_type": "memory-note",
                "access": m["access"],
            }
        )
        + "\n---\n"
        + m["text"]
    )
    # JSON is valid YAML, so the front matter carries the inherited access rule
    res = t.ingest(body.encode("utf-8"), f"memory-{mid}.md", actor=m["owner"], source="memory", doc_id=f"memory-{mid}")
    t.store.update_row(memories, {"id": mid}, doc_id=res["doc_id"])


def review(t: Tenant, p: Principal, mid: int, approve: bool) -> dict[str, Any]:
    if not p.can("curate"):
        raise PermissionError("needs the 'curate' grant (knowledge manager)")
    m = get(t, mid)
    if m["status"] != "proposed":
        raise ValueError("not awaiting review")
    t.store.update_row(memories, {"id": mid}, status="approved" if approve else "rejected")
    t.audit.record(p.user_id, "memory_review", memory_id=mid, approved=approve)
    if approve:
        _index(t, mid)
    return get(t, mid)


def delete(t: Tenant, p: Principal, mid: int) -> None:
    m = get(t, mid)
    if m["owner"] != p.user_id and not p.can("curate"):
        raise PermissionError("only the owner or a knowledge manager can delete")
    if m["doc_id"]:
        chunk_ids = [c["chunk_id"] for c in t.store.all_chunks(t.id) if c["doc_id"] == m["doc_id"]]
        t.index.delete(chunk_ids)
        t.tombstone(m["doc_id"], p.user_id, "memory erased")
    t.store.update_row(memories, {"id": mid}, status="erased", text="[erased]")
    t.audit.record(p.user_id, "memory_erase", memory_id=mid)


def visible(t: Tenant, p: Principal) -> list[dict[str, Any]]:
    out = []
    for m in t.store.rows(memories, order_by="id", tenant=t.id):
        if m["status"] == "erased":
            continue
        mine = m["owner"] == p.user_id
        reviewable = m["status"] == "proposed" and p.can("curate")
        readable = m["status"] == "approved" and evaluate(p, json.loads(m["access"]), "memory-note").allowed
        if mine or reviewable or readable:
            out.append(
                {
                    **m,
                    "provenance": json.loads(m["provenance"] or "[]"),
                    "access": json.loads(m["access"]),
                    "mine": mine,
                }
            )
    return out
