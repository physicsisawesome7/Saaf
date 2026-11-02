"""Deterministic checks for a notice inviting tender."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from smriti.metadata import to_iso


def run(ctx: Any, inputs: dict[str, Any]) -> dict[str, Any]:
    text = inputs.get("tender_text") or ""
    low = text.lower()
    notice = str(inputs.get("notice_date") or date.today().isoformat())
    cfg = ctx.config("checklist.yaml")
    findings: list[dict[str, Any]] = []

    for name, phrases in (cfg.get("annexures") or {}).items():
        ok = any(ph.lower() in low for ph in phrases)
        findings.append(
            {
                "check": f"annexure:{name}",
                "severity": "pass" if ok else "critical",
                "message": f"{name.replace('_', ' ').capitalize()} {'present' if ok else 'missing'}.",
                "citation": None,
            }
        )

    refs = sorted(
        {m.group(1) for m in re.finditer(r"Clause\s+(\d{1,3}(?:\.\d{1,3}){0,3})\s+of\s+(?:the\s+)?GCC", text, re.I)}
    )
    gcc = ctx.tenant.store.find_by_ref(ctx.tenant.id, "GCC")
    for cl in refs:
        exists = bool(gcc and ctx.tenant.store.clause_chunks(ctx.tenant.id, gcc["doc_id"], cl))
        findings.append(
            {
                "check": f"clause_ref:{cl}",
                "severity": "pass" if exists else "major",
                "message": f"Clause {cl} of GCC {'resolves' if exists else 'does not exist in the GCC in force'}.",
                "citation": {
                    "doc_id": gcc["doc_id"],
                    "title": gcc["title"],
                    "ref_no": gcc["ref_no"],
                    "clause_id": cl,
                    "section": "",
                    "date": gcc["doc_date"],
                }
                if gcc and exists
                else None,
            }
        )

    slips = []
    for p in ctx.search("general conditions of contract correction slip", as_of=notice, top_k=8):
        m = re.search(r"Correction\s+Slip\s+(?:No\.?\s*)?(\d+)", p.title + " " + (p.ref_no or ""), re.I)
        if m and p.doc_type == "correction-slip":
            slips.append((int(m.group(1)), p))
    cited = [int(x) for x in re.findall(r"Correction\s+Slip\s+(?:No\.?\s*)?(\d+)", text, re.I)]
    if slips:
        latest, lp = max(slips, key=lambda x: x[0])
        ok = bool(cited) and max(cited) >= latest
        findings.append(
            {
                "check": "slips_current",
                "severity": "pass" if ok else "major",
                "message": f"Document cites slips up to {max(cited) if cited else 'none'}; latest in force on {notice} is {latest}.",
                "citation": ctx.cite(lp),
            }
        )

    m = re.search(r"(?:bid|tender)\s+closing\s+(?:date)?\s*[:\-]?\s*(.{6,24})", text, re.I)
    closing = to_iso(m.group(1)) if m else None
    if closing:
        days = (date.fromisoformat(closing) - date.fromisoformat(notice)).days
        ok = days >= int(cfg.get("min_bid_days", 21))
        findings.append(
            {
                "check": "bid_period",
                "severity": "pass" if ok else "major",
                "message": f"Bid period is {days} days (minimum {cfg.get('min_bid_days', 21)}).",
                "citation": None,
            }
        )
    else:
        findings.append(
            {"check": "bid_period", "severity": "major", "message": "No bid closing date found.", "citation": None}
        )
    return {
        "fields": {"gcc_clauses_cited": refs, "slips_cited": cited, "bid_closing": closing, "notice_date": notice},
        "findings": findings,
    }
