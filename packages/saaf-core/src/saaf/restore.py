"""Tolerant restore: put original values back into LLM output.

Models rarely echo tokens byte-for-byte. Restore accepts:

* case changes            ``[aadhaar_1]``
* dropped brackets        ``AADHAAR_1``
* spaces for underscores  ``[AADHAAR 1]``
* markdown escaping       ``\\[AADHAAR_1\\]``, ``**[AADHAAR_1]**``
* possessives / punctuation ``[AADHAAR_1]'s``
* JSON tool-call arguments (see :func:`restore_json`)
* re-grouped fakes        ``1234-5678-9012`` for a fake issued as ``1234 5678 9012``

``AADHAAR_1`` never matches inside ``AADHAAR_10``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from saaf.policy import UnknownTokenPolicy
from saaf.tokens import TOKEN_SHAPE, is_bracket_token
from saaf.vault import Vault, VaultEntry


@dataclass
class RestoreResult:
    text: str
    restored: int = 0
    missing: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


def token_pattern(token: str) -> str:
    """Tolerant regex source for one issued token."""
    if is_bracket_token(token):
        core = token[1:-1]
        sep = "#" if "#" in core else "_"
        entity, _, suffix = core.rpartition(sep)
        entity_rx = r"[_ \-]?".join(re.escape(part) for part in entity.split("_"))
        return (
            r"(?<![A-Za-z0-9_])(?:\\?\[\s*)?"
            + entity_rx
            + r"[_ \-#]"
            + re.escape(suffix)
            + r"(?![A-Za-z0-9])(?:\s*\\?\])?"
        )
    digits = [ch for ch in token if ch.isdigit()]
    if digits and len(digits) >= 0.6 * len(token.replace(" ", "")):
        lead = r"\+?" if token.startswith("+") else ""
        return r"(?<![0-9])" + lead + r"[ \-]?".join(digits) + r"(?![0-9])"
    return re.escape(token)


def _literal(value: str) -> Callable[[re.Match[str]], str]:
    """Replacement callable, so backslashes in values are never treated as
    regex template escapes."""
    return lambda _m: value


class Restorer:
    def __init__(self, vault: Vault, on_unknown: UnknownTokenPolicy = "leave"):
        self.vault = vault
        self.on_unknown = on_unknown
        self._cache_key: tuple[str, ...] = ()
        self._compiled: list[tuple[re.Pattern[str], VaultEntry]] = []

    def _patterns(self) -> list[tuple[re.Pattern[str], VaultEntry]]:
        entries = sorted(self.vault.entries(), key=lambda e: -len(e.token))
        key = tuple(e.token for e in entries)
        if key != self._cache_key:
            self._compiled = [(re.compile(token_pattern(e.token), re.IGNORECASE), e) for e in entries]
            self._cache_key = key
        return self._compiled

    def tokens(self) -> list[str]:
        return [e.token for _, e in self._patterns()]

    def restore(self, text: str, *, expected: list[str] | None = None) -> RestoreResult:
        result = RestoreResult(text)
        seen: set[str] = set()
        out = text
        for rx, entry in self._patterns():
            out, n = rx.subn(_literal(entry.original), out)
            if n:
                result.restored += n
                seen.add(entry.token)

        def unknown(m: re.Match[str]) -> str:
            result.unknown.append(m.group(0))
            if self.on_unknown == "strip":
                return ""
            if self.on_unknown == "flag":
                return f"[UNVERIFIED {m.group(1)}_{m.group(2)}]"
            return m.group(0)

        out = TOKEN_SHAPE.sub(unknown, out)
        if expected is not None:
            result.missing = [t for t in expected if t not in seen]
        result.text = out
        return result

    def restore_json(self, value: Any) -> Any:
        """Restore every string in a JSON-like structure. Strings that are
        themselves JSON documents (tool-call ``arguments``) are parsed,
        restored and re-serialized so values are escaped correctly."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped[:1] in "{[" and stripped[-1:] in "}]":
                try:
                    parsed = json.loads(value)
                except ValueError:
                    pass
                else:
                    return json.dumps(self.restore_json(parsed), ensure_ascii=False)
            return self.restore(value).text
        if isinstance(value, list):
            return [self.restore_json(v) for v in value]
        if isinstance(value, dict):
            return {k: self.restore_json(v) for k, v in value.items()}
        return value
