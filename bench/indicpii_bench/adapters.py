"""Detector adapters. Each returns ``[(start, end, ENTITY), ...]`` for a text,
with entity names mapped onto Saaf's ids so scores are comparable.

Competitor adapters are written during the Phase 0 teardown (see
docs/DEVELOPMENT_PLAN.md, task P0-3). Until then they raise
``AdapterUnavailable`` with install instructions instead of guessing an API.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

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
    "IN_GSTIN": "GSTIN",
    "PHONE_NUMBER": "PHONE_IN",
    "EMAIL_ADDRESS": "EMAIL",
    "CREDIT_CARD": "CREDIT_CARD",
    "PERSON": "PERSON",
    # added by saaf-presidio
    "IN_UPI_ID": "UPI_ID",
    "IN_IFSC": "IFSC",
    "IN_MOBILE": "PHONE_IN",
    "IN_BANK_ACCOUNT": "BANK_ACCOUNT",
    "IN_ABHA_NUMBER": "ABHA_NUMBER",
    "IN_ABHA_ADDRESS": "ABHA_ADDRESS",
    "IN_DRIVING_LICENSE": "DRIVING_LICENSE",
    "IN_TAN": "TAN",
    "IN_UDYAM": "UDYAM",
    "IN_PIN_CODE": "PIN_CODE",
    "DATE_OF_BIRTH": "DATE_OF_BIRTH",
}
PRESIDIO_INSTALL = "use .venv-bench: pip install presidio-analyzer && python -m spacy download en_core_web_lg"


def _presidio_engine(*, india: bool, saaf: bool) -> Any:
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
    except ImportError as exc:
        raise AdapterUnavailable(PRESIDIO_INSTALL) from exc
    try:
        nlp = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
            }
        ).create_engine()
    except OSError as exc:
        raise AdapterUnavailable(PRESIDIO_INSTALL) from exc
    engine = AnalyzerEngine(nlp_engine=nlp)
    if india and not saaf:
        # Presidio ships these disabled by default; turn every one on (strongest config).
        from presidio_analyzer.predefined_recognizers import (
            InAadhaarRecognizer,
            InGstinRecognizer,
            InPanRecognizer,
            InPassportRecognizer,
            InVehicleRegistrationRecognizer,
            InVoterRecognizer,
        )

        for cls in (
            InAadhaarRecognizer,
            InGstinRecognizer,
            InPanRecognizer,
            InPassportRecognizer,
            InVehicleRegistrationRecognizer,
            InVoterRecognizer,
        ):
            engine.registry.add_recognizer(cls())
    if saaf:
        try:
            from saaf_presidio import add_saaf
        except ImportError as exc:
            raise AdapterUnavailable("add plugins/presidio/src to PYTHONPATH") from exc
        add_saaf(engine.registry)
    return engine


def _presidio_runner(engine: Any, threshold: float) -> Adapter:
    def run(text: str) -> list[Span]:
        return [
            (r.start, r.end, PRESIDIO_MAP[r.entity_type])
            for r in engine.analyze(text=text, language="en")
            if r.entity_type in PRESIDIO_MAP and r.score >= threshold
        ]

    return run


def presidio_default() -> Adapter:
    """Presidio as installed: India recognizers off, score >= 0.5."""
    return _presidio_runner(_presidio_engine(india=False, saaf=False), 0.5)


# Chosen by `indicpii_bench sweep presidio-tuned` on a separate dev seed (see results/README).
PRESIDIO_TUNED_THRESHOLD = 0.4


def presidio_tuned() -> Adapter:
    """Presidio at its best: all six India recognizers on, swept threshold."""
    return _presidio_runner(_presidio_engine(india=True, saaf=False), PRESIDIO_TUNED_THRESHOLD)


def presidio_saaf() -> Adapter:
    """Presidio's spaCy NER for names + Saaf for Indian identifiers (the integration story)."""
    return _presidio_runner(_presidio_engine(india=False, saaf=True), 0.5)


def _pending(name: str, install: str) -> Callable[[], Adapter]:
    def factory() -> Adapter:
        raise AdapterUnavailable(f"{name} adapter not written yet (Phase 0 teardown). Install with: {install}")

    return factory


ADAPTERS: dict[str, Callable[[], Adapter]] = {
    "saaf": saaf_adapter,
    "regex-baseline": regex_baseline,
    "presidio": presidio_default,
    "presidio-tuned": presidio_tuned,
    "presidio+saaf": presidio_saaf,
    "armos": _pending("Armos", "pip install armos"),
    "pygovernor": _pending("pygovernor (svitch)", "pip install svitch"),
    "bharat-pii": _pending("bharat-pii", "pip install bharat-pii"),
    "llm-guard": _pending("LLM Guard", "pip install llm-guard"),
}
