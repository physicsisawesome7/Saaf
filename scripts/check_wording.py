#!/usr/bin/env python3
"""Fail if public-facing files claim compliance.

Saaf provides evidence and safeguards; it never certifies compliance. Lines
that explicitly negate the claim ("not a compliance certification", "not ...
compliant") are allowed, as are references to competitors' claims inside docs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CLAIM = re.compile(r"\b(dpdp[- ]?compliant|compliance[- ]guaranteed|fully compliant|ensures? compliance)\b", re.I)
NEGATION = re.compile(r"\b(not|never|no|isn't|is not|pitched as|claims?|market(?:s|ed)?)\b", re.I)
SKIP = {"scripts/check_wording.py"}


def main(paths: list[str]) -> int:
    bad = []
    for p in paths:
        if p.replace("\\", "/") in SKIP:
            continue
        try:
            lines = Path(p).read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for n, line in enumerate(lines, 1):
            if CLAIM.search(line) and not NEGATION.search(line):
                bad.append(f"{p}:{n}: {line.strip()}")
    if bad:
        print("Compliance claims found (say 'evidence and safeguards' instead):", *bad, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
