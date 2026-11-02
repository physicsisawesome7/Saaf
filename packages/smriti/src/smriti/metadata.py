"""Rule-first metadata extraction.

Rules pull out what they can reliably (reference numbers, dates, document
type, "supersedes" phrases, clause cross-references). The LLM fills the rest
as schema-constrained JSON only when a model is configured, and never
overrides a rule hit. Front matter in Markdown files wins over both, which is
how curated seed documents carry exact metadata.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import yaml

MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        1,
    )
}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9

DATE_PATTERNS = [
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b"),
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b"),
    re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b"),
]

REF_PATTERNS = [
    re.compile(r"\b(?:Correction\s+Slip\s+No\.?\s*)(\d+)\b", re.I),
    re.compile(
        r"\b(?:Letter|Circular|Ref(?:erence)?|File|Tender|Notice|RBE|Order)\s*No\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/().\-]{3,60}[A-Z0-9)])",
        re.I,
    ),
    re.compile(r"\bNo\.\s*([A-Z0-9][A-Z0-9/().\-]{5,60}[A-Z0-9)])"),
]

SUPERSEDE = re.compile(
    r"(?:in\s+supersession\s+of|supersedes|stands?\s+superseded\s+by|hereby\s+cancels?)\s+(?:the\s+)?(?:board'?s?\s+)?"
    r"(?:letter|circular|order|instructions?|notification)?\s*(?:No\.?\s*)?([A-Z0-9][A-Z0-9/().\-]{3,60}[A-Z0-9)])",
    re.I,
)
MODIFY = re.compile(
    r"(?:in\s+partial\s+modification\s+of|amend(?:s|ment\s+to|ing)|correction\s+slip\s+(?:no\.?\s*\d+\s+)?to)\s+(?:the\s+)?"
    r"(?:letter|circular|order|instructions?)?\s*(?:No\.?\s*)?([A-Z0-9][A-Za-z0-9/().\-]{2,60}[A-Za-z0-9)])",
    re.I,
)
CLAUSE_REF = re.compile(
    r"\bClause\s+(\d{1,3}(?:\.\d{1,3}){0,3})(?:\s*\([a-z0-9]+\))?\s+of\s+(?:the\s+)?([A-Z][A-Za-z0-9/\-]{1,30})", re.I
)
CLAUSE_SUBST = re.compile(
    r"\bClause\s+(\d{1,3}(?:\.\d{1,3}){0,3})\b[^.]{0,200}?\b(?:shall\s+be\s+(?:read|substituted|replaced|deleted|inserted)|is\s+(?:hereby\s+)?(?:amended|substituted|replaced))",
    re.I,
)
EFFECTIVE = re.compile(r"(?:with\s+effect\s+from|w\.e\.f\.?|effective\s+(?:from|date)?:?)\s+(.{6,30})", re.I)


def to_iso(s: str) -> str | None:
    for pat in DATE_PATTERNS:
        m = pat.search(s)
        if not m:
            continue
        g = m.groups()
        try:
            if pat is DATE_PATTERNS[0]:
                return date(int(g[0]), int(g[1]), int(g[2])).isoformat()
            if pat is DATE_PATTERNS[1]:
                return date(int(g[2]), int(g[1]), int(g[0])).isoformat()
            if pat is DATE_PATTERNS[2]:
                mon = MONTHS.get(g[1].lower())
                if mon:
                    return date(int(g[2]), mon, int(g[0])).isoformat()
            if pat is DATE_PATTERNS[3]:
                mon = MONTHS.get(g[0].lower())
                if mon:
                    return date(int(g[2]), mon, int(g[1])).isoformat()
        except ValueError:
            continue
    return None


def front_matter(data: bytes) -> dict[str, Any]:
    try:
        text = data[:20000].decode("utf-8-sig")
    except UnicodeDecodeError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        meta = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}
    return meta if isinstance(meta, dict) else {}


def classify(text: str, title: str, schemas: dict[str, Any]) -> str:
    """Pick the schema whose keywords score highest in the title and opening text."""
    head = (title + "\n" + text[:3000]).lower()
    best, best_score = "document", 0
    for name, sch in schemas.items():
        score = 0
        for kw in sch.get("match", []):
            k = kw.lower()
            score += 3 * title.lower().count(k) + head.count(k)
        if score > best_score:
            best, best_score = name, score
    return best


def extract(text: str, title: str, schemas: dict[str, Any], hints: dict[str, Any] | None = None) -> dict[str, Any]:
    hints = hints or {}
    head = text[:4000]
    meta: dict[str, Any] = {}
    meta["doc_type"] = hints.get("doc_type") or classify(text, title, schemas)

    ref = hints.get("ref_no")
    if not ref:
        for pat in REF_PATTERNS:
            m = pat.search(head)
            if m:
                ref = m.group(1).rstrip(".,)") if pat is not REF_PATTERNS[0] else f"Correction Slip {m.group(1)}"
                break
    meta["ref_no"] = ref

    d = hints.get("date")
    meta["doc_date"] = str(d) if d else None
    if not meta["doc_date"]:
        m = re.search(r"(?:dated|date[d:]?)\s*[:\-]?\s*(.{6,30})", head, re.I)
        meta["doc_date"] = to_iso(m.group(1)) if m else to_iso(head)

    eff = hints.get("effective_from")
    if not eff:
        m = EFFECTIVE.search(text)
        eff = to_iso(m.group(1)) if m else None
    meta["effective_from"] = str(eff) if eff else meta["doc_date"]
    meta["valid_until"] = str(hints["valid_until"]) if hints.get("valid_until") else None

    rels: list[dict[str, Any]] = []
    for s in _as_list(hints.get("supersedes")):
        rels.append({"rel_type": "supersedes", "dst_ref": s, "evidence": "declared in front matter"})
    for s in _as_list(hints.get("modifies")):
        if isinstance(s, dict):
            for cl in _as_list(s.get("clauses")) or [None]:
                rels.append(
                    {
                        "rel_type": "modifies",
                        "dst_ref": s["ref"],
                        "clause_id": cl,
                        "evidence": "declared in front matter",
                    }
                )
        else:
            rels.append({"rel_type": "modifies", "dst_ref": s, "evidence": "declared in front matter"})
    if not rels:
        for m in SUPERSEDE.finditer(text):
            rels.append(
                {"rel_type": "supersedes", "dst_ref": m.group(1).rstrip(".,"), "evidence": _snip(text, m.start())}
            )
        for m in MODIFY.finditer(text):
            target = m.group(1).rstrip(".,")
            clauses = sorted({c.group(1) for c in CLAUSE_SUBST.finditer(text)}) or [None]
            for cl in clauses:
                rels.append(
                    {"rel_type": "modifies", "dst_ref": target, "clause_id": cl, "evidence": _snip(text, m.start())}
                )
    # cross-references ("Clause 16.1 of GCC") become refers_to edges: the basis of impact analysis
    seen = set()
    for m in CLAUSE_REF.finditer(text):
        key = (m.group(2).upper(), m.group(1))
        if key in seen:
            continue
        seen.add(key)
        rels.append(
            {
                "rel_type": "refers_to",
                "dst_ref": m.group(2),
                "clause_id": m.group(1),
                "evidence": _snip(text, m.start()),
            }
        )
    for r in _as_list(hints.get("refers_to")):
        if isinstance(r, dict):
            for cl in _as_list(r.get("clauses")) or [None]:
                rels.append(
                    {
                        "rel_type": "refers_to",
                        "dst_ref": r["ref"],
                        "clause_id": cl,
                        "evidence": "declared in front matter",
                    }
                )
    meta["relations"] = rels
    return meta


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _snip(text: str, at: int, width: int = 160) -> str:
    s = max(0, at - 20)
    return re.sub(r"\s+", " ", text[s : s + width]).strip()
