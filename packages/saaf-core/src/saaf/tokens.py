"""Token formats.

label  ``[AADHAAR_1]`` -- default. Same value -> same token within a session.
hmac   ``[AADHAAR_3fa2b1c9]`` -- keyed HMAC, deterministic per tenant key, so the
       same value gets the same token across sessions without storing a counter.
fake   format-preserving fake that can never belong to a real person
       (e.g. an Aadhaar starting with 1, which UIDAI never issues). Falls back
       to ``label`` for entities without a fake generator.
hash   ``[AADHAAR#3fa2b1c9]`` -- used by the ``hash`` action; irreversible.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import re
import secrets

from saaf.validators import verhoeff_check_digit

# Matches any label/hmac-style token, including ones the vault never issued.
TOKEN_SHAPE = re.compile(r"\[([A-Z][A-Z0-9_]*?)_([0-9]+|[0-9a-f]{8})\]")


def label_token(entity: str, index: int) -> str:
    return f"[{entity}_{index}]"


def keyed_digest(key: bytes, entity: str, canonical: str, length: int = 8) -> str:
    return _hmac.new(key, f"{entity}\x1f{canonical}".encode(), hashlib.sha256).hexdigest()[:length]


def hmac_token(key: bytes, entity: str, canonical: str) -> str:
    return f"[{entity}_{keyed_digest(key, entity, canonical)}]"


def hash_token(key: bytes, entity: str, canonical: str) -> str:
    return f"[{entity}#{keyed_digest(key, entity, canonical)}]"


def is_bracket_token(token: str) -> bool:
    return token.startswith("[") and token.endswith("]")


# --- format-preserving fakes ----------------------------------------------


def _regroup(digits: str, template: str) -> str:
    """Lay ``digits`` out with the same separators as ``template``."""
    out, it = [], iter(digits)
    for ch in template:
        out.append(next(it) if ch.isdigit() else ch)
    return "".join(out) + "".join(it)


def fake_aadhaar(original: str) -> str:
    """Verhoeff-valid, starts with 1 -> cannot be a real Aadhaar."""
    payload = "1" + "".join(secrets.choice("0123456789") for _ in range(10))
    return _regroup(payload + verhoeff_check_digit(payload), original)


def fake_in_mobile(original: str) -> str:
    """10 digits starting with 5 -> not an allocated Indian mobile range.
    Keeps any +91/0 prefix and grouping of the original."""
    digits_in_original = sum(ch.isdigit() for ch in original)
    body = "5" + "".join(secrets.choice("0123456789") for _ in range(9))
    prefix_len = digits_in_original - 10
    prefix = "".join(ch for ch in original if ch.isdigit())[:prefix_len] if prefix_len > 0 else ""
    return _regroup(prefix + body, original)


FAKERS = {
    "aadhaar": fake_aadhaar,
    "in_mobile": fake_in_mobile,
}
