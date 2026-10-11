"""Detection: candidate matching, validation, context scoring, OCR repair and
overlap resolution.

Pipeline for one text::

    normalize -> regex candidates -> canonicalize -> validate -> score
              -> OCR-repair candidates (checksum-assisted)
              -> threshold -> resolve overlaps -> map spans to original
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from saaf.normalize import Normalized, normalize
from saaf.spec import EntitySpec, Spec, canonicalize, default_spec

LETTER_TO_DIGIT = {"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"}
DIGIT_TO_LETTERS = {"0": ("O",), "1": ("I", "L"), "5": ("S",), "8": ("B",)}
MAX_OCR_VARIANTS = 64
SEPARATORS = " -"


@dataclass(frozen=True)
class Finding:
    """One detected entity. ``start``/``end`` index the *original* text."""

    entity: str
    start: int
    end: int
    text: str
    score: float
    canonical: str
    severity: str = "medium"
    validated: bool = False
    context_hit: bool = False
    detector: str = "regex"
    ocr_repaired: bool = False
    repaired_value: str | None = None
    priority: int = field(default=50, repr=False, compare=False)

    def to_dict(self, *, include_text: bool = False) -> dict[str, object]:
        """Serializable form. Raw values are excluded unless asked for."""
        d: dict[str, object] = {
            "entity": self.entity,
            "start": self.start,
            "end": self.end,
            "score": round(self.score, 3),
            "severity": self.severity,
            "validated": self.validated,
            "context_hit": self.context_hit,
            "detector": self.detector,
        }
        if self.ocr_repaired:
            d["ocr_repaired"] = True
        if include_text:
            d["text"] = self.text
        return d


class _ContextMatcher:
    """Keyword-in-window matcher. ASCII keywords need word boundaries; Indic
    script keywords match as substrings."""

    def __init__(self, keywords: Sequence[str]):
        ascii_kw = [k for k in keywords if k.isascii()]
        self._other = tuple(k for k in keywords if not k.isascii())
        self._rx = (
            re.compile(
                r"(?<![a-z0-9])(?:"
                + "|".join(re.escape(k) for k in sorted(ascii_kw, key=len, reverse=True))
                + r")(?![a-z0-9])"
            )
            if ascii_kw
            else None
        )

    def nearest(self, before: str, after: str) -> int | None:
        """Distance in characters from the candidate to the closest keyword
        (searching backwards in ``before`` and forwards in ``after``)."""
        best: int | None = None

        def take(d: int) -> None:
            nonlocal best
            best = d if best is None else min(best, d)

        if self._rx is not None:
            hits = list(self._rx.finditer(before))
            if hits:
                take(len(before) - hits[-1].end())
            m = self._rx.search(after)
            if m:
                take(m.start())
        for k in self._other:
            i = before.rfind(k)
            if i >= 0:
                take(len(before) - i - len(k))
            j = after.find(k)
            if j >= 0:
                take(j)
        return best


# Negative context ("order", "ref", ...) only counts inside the candidate's own
# line and sentence, so a label on a neighbouring line cannot suppress it.
_CLAUSE_BREAK = re.compile(r"[\n.!?;](?:\s|$)|\n")


class Detector:
    """Stateless, thread-safe detector compiled from a :class:`Spec`."""

    def __init__(
        self,
        spec: Spec | None = None,
        *,
        entities: Iterable[str] | None = None,
        threshold: float | None = None,
        context_window: int | None = None,
        ocr_repair: bool = True,
    ):
        self.spec = spec or default_spec()
        allowed = set(entities) if entities is not None else None
        if allowed is not None:
            unknown = allowed - set(self.spec.by_id)
            if unknown:
                raise KeyError(f"unknown entities: {sorted(unknown)}")
        self.entities: tuple[EntitySpec, ...] = tuple(
            e for e in self.spec.entities if allowed is None or e.id in allowed
        )
        self.threshold = self.spec.threshold if threshold is None else threshold
        self.window = self.spec.context_window if context_window is None else context_window
        self.ocr_repair = ocr_repair
        self._ctx = {e.id: _ContextMatcher(e.context) for e in self.entities}
        self._neg = {e.id: _ContextMatcher(e.negative_context) for e in self.entities}

    # -- public -----------------------------------------------------------

    def scan(self, text: str, *, threshold: float | None = None) -> list[Finding]:
        """Return non-overlapping findings at or above ``threshold``."""
        norm = normalize(text)
        cut = self.threshold if threshold is None else threshold
        candidates = list(self._candidates(text, norm))
        kept = [f for f in candidates if f.score >= cut]
        return resolve_overlaps(kept)

    def scan_all(self, text: str) -> list[Finding]:
        """Every scored candidate, before threshold and overlap resolution.
        Useful for debugging and false-positive triage."""
        return list(self._candidates(text, normalize(text)))

    # -- internals --------------------------------------------------------

    def _window(self, ntext: str, start: int, end: int) -> tuple[str, str]:
        return ntext[max(0, start - self.window) : start].lower(), ntext[end : end + self.window].lower()

    def _score(self, e: EntitySpec, base: float, window: tuple[str, str]) -> tuple[float, bool] | None:
        before, after = window
        pos = self._ctx[e.id].nearest(before, after) if e.context else None
        hit = pos is not None
        if e.requires_context and not hit:
            return None
        score = base + (e.context_boost if hit else 0.0)
        if e.negative_context:
            breaks = list(_CLAUSE_BREAK.finditer(before))
            clause_before = before[breaks[-1].end() :] if breaks else before
            m = _CLAUSE_BREAK.search(after)
            clause_after = after[: m.start()] if m else after
            neg = self._neg[e.id].nearest(clause_before, clause_after)
            # The nearest label wins: "Mobile: X (ref: Y)" keeps X.
            if neg is not None and (pos is None or neg < pos):
                score -= e.negative_penalty
        return round(max(0.0, min(1.0, score)), 6), hit

    def _candidates(self, original: str, norm: Normalized) -> Iterable[Finding]:
        ntext = norm.text
        for e in self.entities:
            for p in e.patterns:
                for m in p.regex.finditer(ntext):
                    s, t = m.span(p.group)
                    if s == t:
                        continue
                    canonical = canonicalize(e.canonical, ntext[s:t])
                    validated = False
                    if e.validator is not None:
                        validated = e.validator(canonical)
                        if not validated and e.on_invalid == "drop":
                            continue
                    base = e.validated_score if validated else e.base_score
                    scored = self._score(e, base, self._window(ntext, s, t))
                    if scored is None:
                        continue
                    os_, ot = norm.to_original(s, t)
                    yield Finding(
                        entity=e.id,
                        start=os_,
                        end=ot,
                        text=original[os_:ot],
                        score=scored[0],
                        canonical=canonical,
                        severity=e.severity,
                        validated=validated,
                        context_hit=scored[1],
                        priority=e.priority,
                    )
            if self.ocr_repair and e.ocr is not None and e.validator is not None:
                yield from self._ocr_candidates(e, original, norm)

    def _ocr_candidates(self, e: EntitySpec, original: str, norm: Normalized) -> Iterable[Finding]:
        assert e.ocr is not None
        assert e.validator is not None
        ntext = norm.text
        for m in e.ocr.regex.finditer(ntext):
            s, t = m.span()
            raw = "".join(ch for ch in ntext[s:t] if ch not in SEPARATORS)
            if sum(ch.isdigit() for ch in raw) < e.ocr.min_digits:
                continue
            passing = [v for v in ocr_variants(raw, e.ocr.shape) if e.validator(canonicalize(e.canonical, v))]
            if not passing:
                continue
            scored = self._score(e, e.ocr.score, self._window(ntext, s, t))
            if scored is None:
                continue
            os_, ot = norm.to_original(s, t)
            yield Finding(
                entity=e.id,
                start=os_,
                end=ot,
                text=original[os_:ot],
                score=scored[0],
                canonical=canonicalize(e.canonical, passing[0]),
                severity=e.severity,
                validated=True,
                context_hit=scored[1],
                detector="ocr",
                ocr_repaired=True,
                repaired_value=passing[0] if len(passing) == 1 else None,
                priority=e.priority,
            )


def ocr_variants(raw: str, shape: str) -> list[str]:
    """Candidate repairs of ``raw`` against a D(igit)/L(etter) ``shape``.

    Returns an empty list when the text already fits the shape (nothing to
    repair) or cannot be made to fit.
    """
    if len(raw) != len(shape):
        return []
    options: list[tuple[str, ...]] = []
    changed = False
    for ch, kind in zip(raw, shape, strict=True):
        if kind == "D":
            if ch.isdigit():
                options.append((ch,))
            elif ch in LETTER_TO_DIGIT:
                options.append((LETTER_TO_DIGIT[ch],))
                changed = True
            else:
                return []
        else:
            if ch.isalpha():
                options.append((ch.upper(),))
            elif ch in DIGIT_TO_LETTERS:
                options.append(DIGIT_TO_LETTERS[ch])
                changed = True
            else:
                return []
    if not changed:
        return []
    return ["".join(v) for v in itertools.islice(itertools.product(*options), MAX_OCR_VARIANTS)]


def resolve_overlaps(findings: Sequence[Finding]) -> list[Finding]:
    """Greedy selection: highest score, then priority, then longest span."""
    ranked = sorted(findings, key=lambda f: (-f.score, -f.priority, -(f.end - f.start), f.start))
    chosen: list[Finding] = []
    for f in ranked:
        if all(f.end <= c.start or f.start >= c.end for c in chosen):
            chosen.append(f)
    return sorted(chosen, key=lambda f: f.start)
