"""Detector adapters. Each returns ``[(start, end, ENTITY), ...]`` for a text,
with entity names mapped onto Saaf's ids so scores are comparable.

Competitor adapters are written during the Phase 0 teardown (see
docs/DEVELOPMENT_PLAN.md, task P0-3). Until then they raise
``AdapterUnavailable`` with install instructions instead of guessing an API.
"""

from __future__ import annotations

import re
from collections.abc import Callable

Span = tuple[int, int, str]
Adapter = Callable[[str], list[Span]]


class AdapterUnavailable(RuntimeError):
    pass


def saaf_adapter() -> Adapter:
    from saaf import Detector

    d = Detector()
    return lambda text: [(f.start, f.end, f.entity) for f in d.scan(text)]


def regex_baseline() -> Adapter:
    """The 'bare regex' approach many tools start from: no checksums, no context."""
    rules = [
        ("AADHAAR", re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")),
        ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
        ("GSTIN", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]\b")),
        ("PHONE_IN", re.compile(r"(?:\+91[ -]?)?\b[6-9]\d{9}\b")),
        ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")),
        ("UPI_ID", re.compile(r"\b[\w.-]+@[a-z]+\b(?!\.)")),
        ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){15}\d\b")),
        ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ]

    def run(text: str) -> list[Span]:
        out: list[Span] = []
        for entity, rx in rules:
            out += [(m.start(), m.end(), entity) for m in rx.finditer(text)]
        return out

    return run


PRESIDIO_MAP = {
    "IN_AADHAAR": "AADHAAR",
    "IN_PAN": "PAN",
    "IN_VOTER": "VOTER_ID",
    "IN_PASSPORT": "PASSPORT_IN",
    "IN_VEHICLE_REGISTRATION": "VEHICLE_REG",
    "PHONE_NUMBER": "PHONE_IN",
    "EMAIL_ADDRESS": "EMAIL",
    "CREDIT_CARD": "CREDIT_CARD",
    "PERSON": "PERSON",
    "IN_GSTIN": "GSTIN",
}


def presidio_adapter() -> Adapter:
    try:
        from presidio_analyzer import AnalyzerEngine
    except ImportError as exc:
        raise AdapterUnavailable("pip install presidio-analyzer && python -m spacy download en_core_web_lg") from exc
    engine = AnalyzerEngine()

    def run(text: str) -> list[Span]:
        res = engine.analyze(text=text, language="en")
        return [
            (r.start, r.end, PRESIDIO_MAP[r.entity_type])
            for r in res
            if r.entity_type in PRESIDIO_MAP and r.score >= 0.5
        ]

    return run


def _pending(name: str, install: str) -> Callable[[], Adapter]:
    def factory() -> Adapter:
        raise AdapterUnavailable(f"{name} adapter not written yet (Phase 0 teardown). Install with: {install}")

    return factory


ADAPTERS: dict[str, Callable[[], Adapter]] = {
    "saaf": saaf_adapter,
    "regex-baseline": regex_baseline,
    "presidio": presidio_adapter,
    "armos": _pending("Armos", "pip install armos"),
    "pygovernor": _pending("pygovernor (svitch)", "pip install svitch"),
    "bharat-pii": _pending("bharat-pii", "pip install bharat-pii"),
    "llm-guard": _pending("LLM Guard", "pip install llm-guard"),
}
