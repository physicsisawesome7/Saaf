"""Saaf recognizers for Microsoft Presidio.

    from presidio_analyzer import AnalyzerEngine
    from saaf_presidio import add_saaf

    analyzer = AnalyzerEngine()
    add_saaf(analyzer.registry)          # replaces Presidio's IN_* recognizers
    analyzer.analyze(text, language="en")

Presidio's built-in India recognizers are disabled by default and English
only. IN_GSTIN never computes the GSTIN check character, IN_PAN has no
validator, and there is no UPI, IFSC, ABHA, Indian mobile or bank-account
type. This pack runs Saaf's checksum-validated, Hinglish/Indic-aware detector
inside Presidio and reports results under Presidio-style entity names.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from presidio_analyzer import AnalysisExplanation, EntityRecognizer, RecognizerResult

from saaf import Detector

__version__ = "0.1.0.dev0"
__all__ = ["ENTITY_MAP", "SaafRecognizer", "add_saaf"]

# Saaf id -> Presidio entity name (existing Presidio names reused where they exist)
ENTITY_MAP: dict[str, str] = {
    "AADHAAR": "IN_AADHAAR",
    "AADHAAR_VID": "IN_AADHAAR_VID",
    "PAN": "IN_PAN",
    "GSTIN": "IN_GSTIN",
    "VOTER_ID": "IN_VOTER",
    "PASSPORT_IN": "IN_PASSPORT",
    "VEHICLE_REG": "IN_VEHICLE_REGISTRATION",
    "DRIVING_LICENSE": "IN_DRIVING_LICENSE",
    "UPI_ID": "IN_UPI_ID",
    "IFSC": "IN_IFSC",
    "PHONE_IN": "IN_MOBILE",
    "BANK_ACCOUNT": "IN_BANK_ACCOUNT",
    "ABHA_NUMBER": "IN_ABHA_NUMBER",
    "ABHA_ADDRESS": "IN_ABHA_ADDRESS",
    "TAN": "IN_TAN",
    "UDYAM": "IN_UDYAM",
    "PIN_CODE": "IN_PIN_CODE",
    "CREDIT_CARD": "CREDIT_CARD",
    "EMAIL": "EMAIL_ADDRESS",
    "DATE_OF_BIRTH": "DATE_OF_BIRTH",
    "SECRET": "IN_SECRET",
}
REVERSE = {v: k for k, v in ENTITY_MAP.items()}
PRESIDIO_INDIA = (
    "InPanRecognizer",
    "InAadhaarRecognizer",
    "InVehicleRegistrationRecognizer",
    "InVoterRecognizer",
    "InPassportRecognizer",
    "InGstinRecognizer",
)


class SaafRecognizer(EntityRecognizer):
    """One recognizer that runs the whole Saaf detector once per text."""

    def __init__(
        self,
        entities: Iterable[str] | None = None,
        threshold: float = 0.5,
        supported_language: str = "en",
        include_person: bool = False,
    ):
        ids = [k for k in ENTITY_MAP if entities is None or k in entities or ENTITY_MAP[k] in entities]
        self._detector = Detector(entities=ids + (["PERSON"] if include_person else []), threshold=threshold)
        self._include_person = include_person
        supported = [ENTITY_MAP[k] for k in ids] + (["PERSON"] if include_person else [])
        super().__init__(
            supported_entities=supported,
            name="SaafRecognizer",
            supported_language=supported_language,
            version=__version__,
        )

    def load(self) -> None:  # detector is built in __init__
        return None

    def analyze(self, text: str, entities: list[str], nlp_artifacts: Any = None) -> list[RecognizerResult]:
        wanted = set(entities or self.supported_entities)
        out = []
        for f in self._detector.scan(text):
            name = "PERSON" if f.entity == "PERSON" else ENTITY_MAP.get(f.entity)
            if name is None or name not in wanted:
                continue
            explanation = AnalysisExplanation(
                recognizer=self.name,
                original_score=f.score,
                pattern_name=f.entity,
                validation_result=f.validated if f.validated else None,
                textual_explanation=f"saaf:{f.detector}" + (" (ocr-repaired)" if f.ocr_repaired else ""),
            )
            out.append(
                RecognizerResult(
                    entity_type=name,
                    start=f.start,
                    end=f.end,
                    score=f.score,
                    analysis_explanation=explanation,
                    recognition_metadata={"recognizer_name": self.name, "recognizer_identifier": self.id},
                )
            )
        return out


def add_saaf(registry: Any, *, replace_builtin_india: bool = True, **kwargs: Any) -> SaafRecognizer:
    """Register Saaf on a Presidio ``RecognizerRegistry``.

    By default Presidio's own India recognizers are removed so the same span
    is not reported twice with different validation rules.
    """
    if replace_builtin_india:
        for name in PRESIDIO_INDIA:
            try:
                registry.remove_recognizer(name)
            except Exception:  # noqa: S112 - absent recognizers are fine
                continue
    rec = SaafRecognizer(**kwargs)
    registry.add_recognizer(rec)
    return rec
