"""Named validator functions referenced by ``spec/entities.json``.

Every validator takes the *canonical* form of a candidate (see
``saaf.spec.canonicalize``) and returns ``True`` if it is structurally valid.
Validators are pure, deterministic and dependency-free so they can be ported
verbatim to TypeScript; ``spec/conformance/validators.jsonl`` pins behaviour.
"""

from __future__ import annotations

from collections.abc import Callable

# --- Verhoeff (Aadhaar, Aadhaar VID) ---------------------------------------

_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def verhoeff(value: str) -> bool:
    if not value.isascii() or not value.isdigit():
        return False
    c = 0
    for i, ch in enumerate(reversed(value)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def verhoeff_check_digit(payload: str) -> str:
    """Return the Verhoeff check digit to append to ``payload``."""
    c = 0
    for i, ch in enumerate(reversed(payload)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def aadhaar(value: str) -> bool:
    """12 digits, first digit 2-9 (UIDAI never issues 0/1), Verhoeff-valid."""
    return len(value) == 12 and value[0] in "23456789" and verhoeff(value)


# --- Luhn (payment cards) --------------------------------------------------


def luhn(value: str) -> bool:
    if not value.isascii() or not value.isdigit() or len(value) < 2:
        return False
    total = 0
    for i, ch in enumerate(reversed(value)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_CARD_PREFIXES = (
    "4",  # Visa
    "51",
    "52",
    "53",
    "54",
    "55",  # Mastercard
    "34",
    "37",  # Amex
    "36",
    "38",
    "300",
    "301",
    "302",
    "303",
    "304",
    "305",  # Diners
    "60",
    "65",
    "81",
    "82",
    "508",
    "353",
    "356",  # RuPay
    "6011",
    "644",
    "645",
    "646",
    "647",
    "648",
    "649",  # Discover
    "35",  # JCB
)


def card(value: str) -> bool:
    if not 13 <= len(value) <= 19 or len(set(value)) == 1:
        return False
    if not (value.startswith(_CARD_PREFIXES) or 2221 <= int(value[:4]) <= 2720):
        return False
    return luhn(value)


# --- PAN / GSTIN / TAN -----------------------------------------------------

PAN_HOLDER_TYPES = frozenset("ABCFGHJLPT")


def pan(value: str) -> bool:
    v = value.upper()
    return (
        len(v) == 10
        and v[:5].isalpha()
        and v[5:9].isdigit()
        and v[9].isalpha()
        and v[3] in PAN_HOLDER_TYPES
        and v.isascii()
    )


GST_STATE_CODES = frozenset([f"{i:02d}" for i in range(1, 39)] + ["97", "99"])
_GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = _GST_CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _GST_CHARS[(36 - total % 36) % 36]


def gstin(value: str) -> bool:
    v = value.upper()
    if len(v) != 15 or not v.isascii() or not v.isalnum():
        return False
    if v[:2] not in GST_STATE_CODES or not pan(v[2:12]):
        return False
    return gstin_check_char(v[:14]) == v[14]


# --- Banking ---------------------------------------------------------------


def ifsc(value: str) -> bool:
    v = value.upper()
    return len(v) == 11 and v[:4].isalpha() and v[4] == "0" and v[5:].isalnum() and v.isascii()


# Handles of the major UPI PSP apps and banks. Unknown handles still score
# via context (``on_invalid: base``), so this list only raises confidence.
UPI_HANDLES = frozenset(
    [
        "okaxis",
        "okhdfcbank",
        "okicici",
        "oksbi",
        "ybl",
        "ibl",
        "axl",
        "paytm",
        "ptyes",
        "ptaxis",
        "pthdfc",
        "ptsbi",
        "upi",
        "apl",
        "yapl",
        "rapl",
        "waicici",
        "wahdfcbank",
        "waaxis",
        "wasbi",
        "axisbank",
        "axisb",
        "icici",
        "hdfcbank",
        "sbi",
        "kotak",
        "kotak811",
        "freecharge",
        "airtel",
        "airtelpaymentsbank",
        "jio",
        "fbl",
        "idfcbank",
        "idfcfirst",
        "indus",
        "pnb",
        "barodampay",
        "unionbankofindia",
        "unionbank",
        "ikwik",
        "mbk",
        "abfspay",
        "timecosmos",
        "naviaxis",
        "superyes",
        "kbl",
        "cnrb",
        "boi",
        "citi",
        "citigold",
        "hsbc",
        "yesbank",
        "yesbankltd",
        "aubank",
        "dbs",
        "federal",
        "rbl",
        "sib",
        "kvb",
        "tjsb",
        "equitas",
        "ujjivan",
        "jupiteraxis",
        "fam",
        "slice",
        "postbank",
        "ippb",
        "dlb",
        "pingpay",
        "pockets",
        "payzapp",
        "idbi",
        "uco",
        "mahb",
        "indianbank",
        "centralbank",
        "iob",
    ]
)


def upi_handle(value: str) -> bool:
    if "@" not in value:
        return False
    user, _, handle = value.rpartition("@")
    return len(user) >= 2 and handle.lower() in UPI_HANDLES


def in_mobile(value: str) -> bool:
    """Canonical digits, optionally prefixed with 91/0; last 10 must be a mobile."""
    digits = value
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        return False
    return len(set(digits[1:])) > 1


# --- Regional codes --------------------------------------------------------

STATE_CODES = frozenset(
    [
        "AN",
        "AP",
        "AR",
        "AS",
        "BR",
        "CH",
        "CG",
        "CT",
        "DD",
        "DL",
        "DN",
        "GA",
        "GJ",
        "HR",
        "HP",
        "JK",
        "JH",
        "KA",
        "KL",
        "LA",
        "LD",
        "MP",
        "MH",
        "MN",
        "ML",
        "MZ",
        "NL",
        "OD",
        "OR",
        "PB",
        "PY",
        "RJ",
        "SK",
        "TN",
        "TS",
        "TG",
        "TR",
        "UP",
        "UK",
        "UA",
        "WB",
    ]
)


def in_state_code(value: str) -> bool:
    return value[:2].upper() in STATE_CODES


def udyam(value: str) -> bool:
    v = value.upper()
    return v.startswith("UDYAM") and v[5:7] in STATE_CODES


VALIDATORS: dict[str, Callable[[str], bool]] = {
    "verhoeff": verhoeff,
    "aadhaar": aadhaar,
    "luhn": luhn,
    "card": card,
    "pan": pan,
    "gstin": gstin,
    "ifsc": ifsc,
    "upi_handle": upi_handle,
    "in_mobile": in_mobile,
    "in_state_code": in_state_code,
    "udyam": udyam,
}


def get_validator(name: str) -> Callable[[str], bool]:
    try:
        return VALIDATORS[name]
    except KeyError:
        raise KeyError(f"unknown validator {name!r}; known: {sorted(VALIDATORS)}") from None
