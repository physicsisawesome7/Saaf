"""Deterministic checks for a Letter of Acceptance.

Thresholds and contract terms are *retrieved* from the documents in force on
the letter date, so a new correction slip or powers letter changes the result
without a code change. Unit-tested with the domain owner's cases in
evals/cases.yaml (planted defects).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

SEV_FAIL = "critical"


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(s))
    return float(m.group(0).replace(",", "")) if m else None


def extract_fields(text: str) -> dict[str, Any]:
    f: dict[str, Any] = {}
    if m := re.search(r"Tender\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{4,40})", text, re.I):
        f["tender_no"] = m.group(1).rstrip(".,")
    if m := re.search(r"(?:Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*(crore|cr|lakh)?", text, re.I):
        v = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        f["value_cr"] = v if unit in ("crore", "cr") else v / 100 if unit == "lakh" else v / 1e7
    if m := re.search(r"(?:completion|completed)[^.]{0,60}?(\d{1,3})\s*months", text, re.I):
        f["completion_months"] = int(m.group(1))
    if m := re.search(r"Performance\s+Guarantee[^.]{0,80}?(\d+(?:\.\d+)?)\s*%", text, re.I):
        f["pg_percent"] = float(m.group(1))
    if m := re.search(r"Performance\s+Guarantee[^.]{0,160}?within\s+(\d{1,3})\s*days", text, re.I):
        f["pg_days"] = int(m.group(1))
    slips = [int(x) for x in re.findall(r"Correction\s+Slip\s+(?:No\.?\s*)?(\d+)", text, re.I)]
    f["slips_cited"] = max(slips) if slips else None
    return f


def run(ctx: Any, inputs: dict[str, Any]) -> dict[str, Any]:
    text = inputs.get("letter_text") or ""
    bid = inputs.get("bid") or {}
    letter_date = str(inputs.get("letter_date") or date.today().isoformat())
    acceptor = (inputs.get("acceptor") or "").strip()
    fields = extract_fields(text)
    llm = (
        ctx.extract(
            "Extract the Letter of Acceptance fields.",
            text,
            {
                "type": "object",
                "properties": {
                    "tender_no": {"type": "string"},
                    "value_cr": {"type": "number"},
                    "completion_months": {"type": "integer"},
                    "pg_percent": {"type": "number"},
                    "pg_days": {"type": "integer"},
                },
            },
        )
        if text
        else None
    )
    for k, v in (llm or {}).items():
        fields.setdefault(k, v)  # rules win; the model only fills gaps

    findings: list[dict[str, Any]] = []

    def add(check: str, ok: bool | None, msg: str, sev: str = SEV_FAIL, cite: dict[str, Any] | None = None) -> None:
        findings.append(
            {
                "check": check,
                "severity": "pass" if ok else ("info" if ok is None else sev),
                "message": msg,
                "citation": cite,
            }
        )

    # ---- bid consistency
    if bid.get("tender_no"):
        ok = (fields.get("tender_no") or "").upper() == str(bid["tender_no"]).upper()
        add(
            "tender_no_matches",
            ok,
            f"Letter cites tender {fields.get('tender_no') or 'none'}; bid is {bid['tender_no']}.",
        )
    if bid.get("value_cr") is not None:
        lv, bv = fields.get("value_cr"), float(bid["value_cr"])
        ok = lv is not None and abs(lv - bv) < 0.005
        add("value_matches", ok, f"Letter value Rs {lv if lv is not None else '?'} crore; bid value Rs {bv} crore.")
    if bid.get("completion_months") is not None:
        ok = fields.get("completion_months") == int(bid["completion_months"])
        add(
            "completion_matches",
            ok,
            f"Letter completion {fields.get('completion_months') or '?'} months; bid {bid['completion_months']} months.",
            "major",
        )

    # ---- performance guarantee: clause 16.1 as amended on the letter date
    ps = ctx.search(
        "performance guarantee clause 16.1 submit within days of contract value", as_of=letter_date, top_k=4
    )
    base = next((p for p in ps if p.clause_id == "16.1" and p.status != "amendment"), None)
    amend = [p for p in ps if p.status == "amendment"]
    gov = amend[-1] if amend else base
    if gov:
        days = _num((re.search(r"within\s+(\d{1,3})\s*days", gov.text) or [None, None])[1])
        pct = _num((re.search(r"(\d+(?:\.\d+)?)\s*%\s*of\s*the\s*contract\s*value", gov.text) or [None, None])[1])
        cite = ctx.cite(gov)
        problems = []
        if days and fields.get("pg_days") and int(days) != fields["pg_days"]:
            problems.append(f"submission period {fields['pg_days']} days, clause requires {int(days)} days")
        if pct and fields.get("pg_percent") and abs(pct - fields["pg_percent"]) > 1e-6:
            problems.append(f"PG {fields['pg_percent']}%, clause requires {pct:g}%")
        if not fields.get("pg_days") and not fields.get("pg_percent"):
            add("pg_terms_current", False, "Letter does not state the Performance Guarantee terms.", "major", cite)
        else:
            src = f"{gov.title}" + (" (amendment in force)" if amend else "")
            add(
                "pg_terms_current",
                not problems,
                ("Performance Guarantee terms match " + src) if not problems else "; ".join(problems) + f" per {src}.",
                SEV_FAIL,
                cite,
            )
    else:
        add("pg_terms_current", None, "Could not retrieve clause 16.1 in force on the letter date.")

    # ---- powers of acceptance in force on the letter date (retrieved, never hard-coded)
    value = fields.get("value_cr") or _num(bid.get("value_cr"))
    poa = ctx.search(
        "powers of acceptance works tenders designation maximum value crore finance vetting", as_of=letter_date, top_k=6
    )
    row = None
    poa_p = None
    for p in poa:
        tbl = ctx.table_rows(p)
        if not tbl:
            continue
        cols, rows = tbl
        for r in rows:
            if acceptor and r and r[0].strip().lower() == acceptor.lower():
                row, poa_p = dict(zip([c.lower() for c in cols], r, strict=False)), p
                break
        if row:
            break
    if row and value is not None:
        cite = ctx.cite(poa_p)
        lim_txt = next((v for k, v in row.items() if "maximum" in k), "")
        limit = float("inf") if "full" in lim_txt.lower() else (_num(lim_txt) or 0)
        add(
            "acceptor_power",
            value <= limit,
            f"{acceptor} may accept up to {lim_txt} crore; this letter is Rs {value} crore.",
            SEV_FAIL,
            cite,
        )
        vet_txt = next((v for k, v in row.items() if "vetting" in k), "")
        threshold = _num(vet_txt)
        if threshold is not None:
            needs = value > threshold
            vetted = bool(inputs.get("finance_vetted"))
            add(
                "finance_vetting",
                (not needs) or vetted,
                f"Associate Finance vetting is {'required' if needs else 'not required'} above Rs {threshold:g} crore; recorded: {'yes' if vetted else 'no'}.",
                SEV_FAIL,
                cite,
            )
    else:
        add(
            "acceptor_power",
            None if not acceptor else False,
            f"No powers-of-acceptance row found for '{acceptor or 'unspecified acceptor'}' in the letter in force.",
            "major",
        )

    # ---- offer validity
    if bid.get("offer_valid_until"):
        ok = letter_date <= str(bid["offer_valid_until"])
        add("offer_validity", ok, f"Letter dated {letter_date}; offer valid until {bid['offer_valid_until']}.")

    # ---- latest correction slip cited
    gcc = ctx.search("general conditions of contract correction slip", as_of=letter_date, top_k=8)
    slips = []
    for p in gcc:
        m = re.search(r"Correction\s+Slip\s+(?:No\.?\s*)?(\d+)", p.title + " " + (p.ref_no or ""), re.I)
        if m and p.doc_type == "correction-slip":
            slips.append((int(m.group(1)), p))
    if slips:
        latest, lp = max(slips, key=lambda x: x[0])
        cited = fields.get("slips_cited")
        add(
            "slips_cited",
            cited is not None and cited >= latest,
            f"Letter cites GCC up to Correction Slip {cited or 'none'}; latest in force on {letter_date} is Slip {latest}.",
            "minor",
            ctx.cite(lp),
        )

    out: dict[str, Any] = {"fields": fields, "findings": findings}
    if inputs.get("make_draft"):
        tpl = ctx.template("loa.md")
        vals = {
            "tender_no": bid.get("tender_no"),
            "value_cr": bid.get("value_cr"),
            "completion_months": bid.get("completion_months"),
            "letter_date": letter_date,
            "acceptor": acceptor or None,
            "pg_percent": f"{pct:g}" if gov and pct else None,
            "pg_days": int(days) if gov and days else None,
            "latest_slip": max(slips, key=lambda x: x[0])[0] if slips else None,
            "contractor": bid.get("contractor"),
            "work": bid.get("work"),
        }
        out["draft"] = re.sub(
            r"\{(\w+)\}",
            lambda m: str(vals[m.group(1)]) if vals.get(m.group(1)) not in (None, "") else f"[[TO FILL: {m.group(1)}]]",
            tpl,
        )
    return out
