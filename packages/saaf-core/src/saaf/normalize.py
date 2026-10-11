"""Text normalization with an offset map back to the original string.

Detection runs on normalized text, but masking must replace spans in the
*original* text. Every normalized character therefore remembers the index of
the original character it came from.

Steps, applied per code point:

* strip zero-width and BOM characters
* fold Indic digits (Devanagari, Bengali, Gurmukhi, ...) to ASCII
* fold Unicode dashes and minus signs to ``-``
* fold common Cyrillic/Greek homoglyphs to Latin
* NFKC (fullwidth digits, NBSP, ligatures, ...)

The TypeScript port (``packages/saaf-js/src/normalize.ts``) must stay in step
with this file; the conformance suite checks that both agree.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

ZERO_WIDTH = frozenset({0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD})

# Zero code point of each Indic digit block.
INDIC_DIGIT_ZEROS = (
    0x0966,  # Devanagari
    0x09E6,  # Bengali
    0x0A66,  # Gurmukhi
    0x0AE6,  # Gujarati
    0x0B66,  # Odia
    0x0BE6,  # Tamil
    0x0C66,  # Telugu
    0x0CE6,  # Kannada
    0x0D66,  # Malayalam
)

DASHES = frozenset({0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0xFE63, 0xFF0D})

HOMOGLYPHS = {
    # Cyrillic
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "Х": "X",
    "У": "Y",
    "І": "I",
    "Ј": "J",
    "Ѕ": "S",
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "х": "x",
    "у": "y",
    "і": "i",
    "ј": "j",
    "ѕ": "s",
    # Greek
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Υ": "Y",
    "Χ": "X",
    "ο": "o",
}


@dataclass(frozen=True)
class Normalized:
    """Normalized text plus ``index_map[i]`` = original index of ``text[i]``."""

    text: str
    index_map: tuple[int, ...]
    original_length: int

    def to_original(self, start: int, end: int) -> tuple[int, int]:
        """Map a half-open span in normalized text back to the original."""
        if start >= end:
            pos = self.index_map[start] if start < len(self.index_map) else self.original_length
            return pos, pos
        return self.index_map[start], self.index_map[end - 1] + 1


def fold_char(ch: str) -> str:
    """Normalize a single code point. May return "" or several characters."""
    cp = ord(ch)
    if cp in ZERO_WIDTH:
        return ""
    for zero in INDIC_DIGIT_ZEROS:
        if zero <= cp <= zero + 9:
            return chr(0x30 + cp - zero)
    if cp in DASHES:
        return "-"
    if ch in HOMOGLYPHS:
        return HOMOGLYPHS[ch]
    if cp < 0x80:
        return ch
    return unicodedata.normalize("NFKC", ch)


def normalize(text: str) -> Normalized:
    out: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(text):
        folded = fold_char(ch)
        out.append(folded)
        index_map.extend([i] * len(folded))
    return Normalized("".join(out), tuple(index_map), len(text))
