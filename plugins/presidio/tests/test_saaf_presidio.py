from __future__ import annotations

import pytest

pytest.importorskip("presidio_analyzer")
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from saaf_presidio import ENTITY_MAP, add_saaf


@pytest.fixture(scope="module")
def analyzer() -> AnalyzerEngine:
    try:
        nlp = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
            }
        ).create_engine()
    except OSError:
        pytest.skip("spaCy model en_core_web_lg not installed")
    a = AnalyzerEngine(nlp_engine=nlp)
    add_saaf(a.registry)
    return a


def found(analyzer: AnalyzerEngine, text: str) -> dict[str, str]:
    return {r.entity_type: text[r.start : r.end] for r in analyzer.analyze(text, language="en") if r.score >= 0.5}


def test_adds_types_presidio_lacks(analyzer: AnalyzerEngine) -> None:
    text = "Pay ravi.kumar@okaxis, IFSC SBIN0001234, call +91 98765 43210"
    got = found(analyzer, text)
    assert got["IN_UPI_ID"] == "ravi.kumar@okaxis"
    assert got["IN_IFSC"] == "SBIN0001234"
    assert got["IN_MOBILE"] == "+91 98765 43210"


def test_real_gstin_check_character(analyzer: AnalyzerEngine) -> None:
    assert found(analyzer, "GSTIN 27ABCPE1234F1ZB")["IN_GSTIN"] == "27ABCPE1234F1ZB"
    # Wrong check character: dropped without a label (Presidio's IN_GSTIN would
    # accept it); kept only when explicitly labelled "GSTIN" (a likely typo).
    assert "IN_GSTIN" not in found(analyzer, "code 27ABCPE1234F1ZC here")
    scores = {
        r.start: r.score
        for r in analyzer.analyze("GSTIN 27ABCPE1234F1ZB, GSTIN 27ABCPE1234F1ZC", language="en")
        if r.entity_type == "IN_GSTIN"
    }
    assert scores[6] > scores[29]  # valid check character scores higher


def test_builtin_india_recognizers_replaced(analyzer: AnalyzerEngine) -> None:
    names = {r.name for r in analyzer.registry.recognizers}
    assert "SaafRecognizer" in names
    assert "InGstinRecognizer" not in names and "InPanRecognizer" not in names


def test_hinglish_and_devanagari(analyzer: AnalyzerEngine) -> None:
    got = found(analyzer, "mera adhaar २३४५ ६७८९ ०१२४ hai aur pan abcpe1234f")
    assert got["IN_AADHAAR"] == "२३४५ ६७८९ ०१२४"
    assert got["IN_PAN"] == "abcpe1234f"


def test_order_id_not_flagged(analyzer: AnalyzerEngine) -> None:
    assert "IN_AADHAAR" not in found(analyzer, "Order ID 234567890124 shipped")


def test_entity_map_is_injective() -> None:
    assert len(set(ENTITY_MAP.values())) == len(ENTITY_MAP)
