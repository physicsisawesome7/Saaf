from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_DIR = REPO_ROOT / "spec"
CONFORMANCE = SPEC_DIR / "conformance"


def load_jsonl(name: str) -> list[dict[str, Any]]:
    path = CONFORMANCE / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# Synthetic identifiers. Every one is checksum-valid but invented.
AADHAAR = "2345 6789 0124"
AADHAAR_2 = "9876 5432 1012"
PAN = "ABCPE1234F"
GSTIN = "27ABCPE1234F1ZB"
MOBILE = "+91 98765 43210"


@pytest.fixture
def kyc_text() -> str:
    return (
        f"Customer KYC: Aadhaar {AADHAAR}, PAN {PAN}, GSTIN {GSTIN}, "
        f"mobile {MOBILE}, UPI ravi.kumar@okaxis, email ravi@example.in"
    )
