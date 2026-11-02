"""Circular impact: what a new slip or circular touches, with redlines."""

from __future__ import annotations

import difflib
import re
from typing import Any

from smriti.access import evaluate


def redline(old: str, new: str) -> str:
    a, b = old.split(), new.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if op == "equal":
            out.append(" ".join(a[i1:i2]))
        if op in ("delete", "replace"):
            out.append("[-" + " ".join(a[i1:i2]) + "-]")
        if op in ("insert", "replace"):
            out.append("{+" + " ".join(b[j1:j2]) + "+}")
    return " ".join(out)


def _amended_text(slip_text: str, clause: str) -> str | None:
    """The replacement wording a slip gives for a clause: the quoted text after
    "shall be read as", or the rest of that line when it is not quoted."""
    head = rf"Clause\s+{re.escape(clause)}\b.*?shall\s+be\s+read\s+as\s*[:\-]?\s*"
    m = re.search(head + r"[\"“](.+?)[\"”]", slip_text, re.I | re.S) or re.search(
        head + r"(.+?)(?:\n|$)", slip_text, re.I | re.S
    )
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def _text_before(t: Any, rel: dict[str, Any]) -> str | None:
    """Wording in force just before this slip: the latest earlier slip for the
    same clause, otherwise the base clause."""
    earlier = [
        r
        for r in t.store.relations_for(t.id, rel["dst_doc"])
        if r["rel_type"] == "modifies"
        and r["dst_doc"] == rel["dst_doc"]
        and r["clause_id"] == rel["clause_id"]
        and r["src_doc"] != rel["src_doc"]
        and (r["effective_from"] or "") < (rel["effective_from"] or "")
    ]
    for r in sorted(earlier, key=lambda r: r["effective_from"] or "", reverse=True):
        text = "\n".join(c["text"] for c in t.store.doc_chunks(t.id, r["src_doc"]))
        if found := _amended_text(text, rel["clause_id"]):
            return found
    base = " ".join(c["text"] for c in t.store.clause_chunks(t.id, rel["dst_doc"], rel["clause_id"]))
    return re.sub(rf"^\s*{re.escape(rel['clause_id'])}\s*", "", base.split("\n")[-1]) if base else None


def run(ctx: Any, inputs: dict[str, Any]) -> dict[str, Any]:
    t, p = ctx.tenant, ctx.principal
    ref = str(inputs.get("document") or "").strip()
    d = t.store.get_document(t.id, ref) or t.store.find_by_ref(t.id, ref)
    if not d or not evaluate(p, d["access"], d["doc_type"]).allowed:
        return {
            "findings": [
                {
                    "check": "document_found",
                    "severity": "major",
                    "message": f"No document you can open matches '{ref}'.",
                    "citation": None,
                }
            ]
        }
    slip_text = "\n\n".join(c["text"] for c in t.store.doc_chunks(t.id, d["doc_id"]))
    findings = []
    redlines = []
    for r in ctx.relations(d["doc_id"]):
        if r["src_doc"] != d["doc_id"] or r["rel_type"] not in ("modifies", "supersedes") or not r["dst_doc"]:
            continue
        base = t.store.get_document(t.id, r["dst_doc"])
        if r["clause_id"]:
            old_body = _text_before(t, r)
            new = _amended_text(slip_text, r["clause_id"])
            if old_body and new:
                redlines.append(
                    {
                        "clause": r["clause_id"],
                        "base_document": base["title"] if base else r["dst_ref"],
                        "old": old_body,
                        "new": new,
                        "redline": redline(old_body, new),
                    }
                )
        findings.append(
            {
                "check": "relation",
                "severity": "info",
                "message": f"{d['title']} {r['rel_type']} {('clause ' + r['clause_id'] + ' of ') if r['clause_id'] else ''}{base['title'] if base else r['dst_ref']} with effect from {r['effective_from']}.",
                "citation": {
                    "doc_id": d["doc_id"],
                    "title": d["title"],
                    "ref_no": d["ref_no"],
                    "clause_id": r["clause_id"],
                    "section": "",
                    "date": d["doc_date"],
                },
            }
        )
    impact = ctx.impact(d["doc_id"])
    for x in impact:
        findings.append(
            {
                "check": "affected_document",
                "severity": "major",
                "message": f"{x['title']} ({x['doc_type']}) cites clause {x['clause_id']} and needs review.",
                "citation": {
                    "doc_id": x["doc_id"],
                    "title": x["title"],
                    "ref_no": None,
                    "clause_id": x["clause_id"],
                    "section": "",
                    "date": None,
                },
            }
        )
        x.pop("access", None)
    if not impact:
        findings.append(
            {
                "check": "affected_document",
                "severity": "pass",
                "message": "No document you can open refers to the changed clauses.",
                "citation": None,
            }
        )
    return {
        "fields": {"document": d["title"], "ref_no": d["ref_no"]},
        "findings": findings,
        "impact": impact,
        "extra": {"redlines": redlines},
    }
