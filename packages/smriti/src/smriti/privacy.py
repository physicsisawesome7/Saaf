"""PII masking, built on Saaf.

Two uses:

* **Field-level masking by role.** Documents stay visible while the PII inside
  them (Aadhaar, PAN, phone, land-owner names) is masked for anyone whose role
  does not unmask that category. Masking for display is one-way.
* **Mask-and-restore for the model.** The user's question is masked before the
  model sees it and the reply is restored afterwards, using Saaf's vault.

Saaf validates identifiers with checksums (Verhoeff, Luhn, PAN rules), so an
order number is not mistaken for an Aadhaar. Names have no checksum, so
documents declare name-bearing columns and labels in their schema.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from saaf import Saaf

_detector = Saaf()

# A name only counts when a label introduces it: "Owner: Ram Prasad",
# "land owner Shri Ram Prasad", "S/o Shiv Charan". Bare phrases such as
# "land owner Aadhaar numbers" are not names.
NAME_LABELS = re.compile(
    r"(?P<label>(?i:(?:(?:land[\s-]?owner|owner|khatedar|name of (?:the )?(?:owner|khatedar|landholder)|father'?s name|"
    r"भूस्वामी|खातेदार|पिता का नाम)\s*(?:[:\-]\s*|\s+(?:Shri|Smt\.?|Sri|Kumari|Mr\.?|Mrs\.?|Ms\.?)\s+)|(?:s/o|d/o|w/o)\s+)))"
    r"(?P<name>(?:[A-Z][a-z]+\.?)(?:\s+[A-Z][a-z]+\.?){0,3}|[ऀ-ॿ]+(?:\s+[ऀ-ॿ]+){0,3})",
)

DEFAULT_NAME_COLUMNS = ("owner", "khatedar", "landholder", "father", "name of", "भूस्वामी", "खातेदार")


def pii_categories(text: str) -> set[str]:
    cats = {f.entity.lower() for f in _detector.scan(text)}
    if NAME_LABELS.search(text):
        cats.add("land_owner_name")
    return cats


def mask_text(text: str, unmask: Iterable[str] = ()) -> tuple[str, set[str]]:
    """Mask every PII category not in ``unmask``. Returns (text, categories masked)."""
    keep = {u.lower() for u in unmask}
    masked: set[str] = set()
    spans: list[tuple[int, int, str]] = []
    for f in _detector.scan(text):
        cat = f.entity.lower()
        if cat in keep:
            continue
        spans.append((f.start, f.end, f"[{f.entity}]"))
        masked.add(cat)
    if "land_owner_name" not in keep:
        for m in NAME_LABELS.finditer(text):
            spans.append((m.start("name"), m.end("name"), "[LAND_OWNER_NAME]"))
            masked.add("land_owner_name")
    out = text
    last = len(text) + 1
    for start, end, tok in sorted(spans, key=lambda s: s[0], reverse=True):
        if end > last:  # overlapping span; the later one already covers it
            continue
        out = out[:start] + tok + out[end:]
        last = start
    return out, masked


def mask_table(
    columns: list[str],
    rows: list[list[str]],
    unmask: Iterable[str] = (),
    name_columns: Iterable[str] = DEFAULT_NAME_COLUMNS,
) -> tuple[list[list[str]], set[str]]:
    keep = {u.lower() for u in unmask}
    name_cols = (
        {i for i, c in enumerate(columns) if any(n in c.lower() for n in name_columns)}
        if "land_owner_name" not in keep
        else set()
    )
    masked: set[str] = set()
    out = []
    for row in rows:
        new = []
        for i, cell in enumerate(row):
            if i in name_cols and cell.strip():
                new.append("[LAND_OWNER_NAME]")
                masked.add("land_owner_name")
            else:
                t, m = mask_text(cell, keep | {"land_owner_name"})
                masked |= m
                new.append(t)
        out.append(new)
    return out, masked


class ConversationMasker:
    """Mask the question on the way to the model; restore the answer on the way back."""

    def __init__(self) -> None:
        self.saaf = Saaf()

    def mask(self, text: str) -> tuple[str, list[str]]:
        r = self.saaf.mask(text)
        return r.text, sorted(r.entity_counts)

    def restore(self, text: str) -> str:
        return self.saaf.restore(text).text
