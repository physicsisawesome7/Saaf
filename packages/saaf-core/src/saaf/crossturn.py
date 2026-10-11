"""Cross-turn detection (P1).

Catches identifiers split across messages or broken up by words::

    turn 1: "my aadhaar starts 2345"
    turn 2: "the rest is 6789 0124"

The tracker keeps the digit groups of the last few turns. When consecutive
groups concatenate to a valid Aadhaar and Aadhaar context appears in the
conversation, the groups in the *current* turn are reported for masking. Groups
in earlier turns have already been sent; they are reported as ``prior_leak`` so
the caller can alert, but cannot be recalled.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass

from saaf.normalize import normalize
from saaf.validators import aadhaar

_GROUP = re.compile(r"(?<![0-9])[0-9]{2,8}(?![0-9])")
_CONTEXT = re.compile(r"(?<![a-z])(?:aadhaa?r|adhaa?r|uid)(?![a-z])|आधार")


@dataclass(frozen=True)
class CrossTurnHit:
    spans: tuple[tuple[int, int], ...]  # original-text spans in the current turn
    prior_leak: bool


class CrossTurnTracker:
    def __init__(self, max_turns: int = 3):
        self._history: deque[tuple[list[str], bool]] = deque(maxlen=max_turns)

    def check(self, text: str) -> list[CrossTurnHit]:
        norm = normalize(text)
        current = [(m.group(0), m.span()) for m in _GROUP.finditer(norm.text)]
        has_ctx = bool(_CONTEXT.search(norm.text.lower())) or any(ctx for _, ctx in self._history)
        prev = [g for groups, _ in self._history for g in groups]
        self._history.append(([g for g, _ in current], bool(_CONTEXT.search(norm.text.lower()))))
        if not has_ctx or not current:
            return []
        combined: list[tuple[str, tuple[int, int] | None]] = [(g, None) for g in prev] + list(current)
        hits: list[CrossTurnHit] = []
        for i in range(len(combined)):
            digits = ""
            for j in range(i, len(combined)):
                digits += combined[j][0]
                if len(digits) > 12:
                    break
                if len(digits) == 12 and j > i and aadhaar(digits):
                    window = combined[i : j + 1]
                    spans = tuple(norm.to_original(*s) for _, s in window if s is not None)
                    if spans:
                        hits.append(CrossTurnHit(spans, prior_leak=any(s is None for _, s in window)))
                    break
        return hits

    def reset(self) -> None:
        self._history.clear()
