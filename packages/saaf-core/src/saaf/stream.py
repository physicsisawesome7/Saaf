"""Streaming-safe restore.

LLM responses arrive in chunks, and a token can be split across them
(``"... [AADH"`` + ``"AAR_1] ..."``). :class:`StreamRestorer` emits everything
that cannot be the start of a token and holds back the shortest suffix that
still could be, until the next chunk resolves it or the stream ends.
"""

from __future__ import annotations

from saaf.restore import Restorer

_TOKENISH = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_[]\\ -+#")


def _squash(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch not in "[]\\ -_+#")


class StreamRestorer:
    def __init__(self, restorer: Restorer, *, max_hold: int | None = None):
        self._r = restorer
        self._buf = ""
        self._max_hold = max_hold
        self.restored = 0
        self.unknown: list[str] = []

    def _forms(self) -> list[str]:
        return [_squash(t) for t in self._r.tokens()]

    def _limit(self, forms: list[str]) -> int:
        if self._max_hold is not None:
            return self._max_hold
        return max((len(f) for f in forms), default=0) * 2 + 8

    def _could_be_prefix(self, suffix: str, forms: list[str]) -> bool:
        if suffix == "\\":
            return True  # may become an escaped bracket
        if suffix.startswith("[") or suffix.startswith("\\["):
            # An unclosed bracket might still become any token, including an
            # unknown one the restorer needs to see whole.
            return "]" not in suffix
        sq = _squash(suffix)
        if not sq:
            return False
        return any(f.startswith(sq) for f in forms)

    def _split(self) -> int:
        """Index in the buffer from which text must be held back."""
        forms = self._forms()
        buf = self._buf
        start = max(0, len(buf) - self._limit(forms))
        for i in range(start, len(buf)):
            if not (buf[i].isalnum() or buf[i] in "[\\+"):
                continue  # a token (or fake) can only start here
            if i > 0 and (buf[i - 1] in "[\\" or (buf[i - 1].isalnum() and buf[i].isalnum())):
                continue  # tokens start at a word boundary, brackets included
            if not all(ch in _TOKENISH for ch in buf[i:]):
                continue
            if self._could_be_prefix(buf[i:], forms):
                return i
        return len(buf)

    def feed(self, chunk: str) -> str:
        """Add a chunk; return the text that is now safe to emit."""
        self._buf += chunk
        cut = self._split()
        ready, self._buf = self._buf[:cut], self._buf[cut:]
        return self._emit(ready)

    def flush(self) -> str:
        """End of stream: restore and emit whatever is still held."""
        ready, self._buf = self._buf, ""
        return self._emit(ready)

    def _emit(self, text: str) -> str:
        if not text:
            return ""
        res = self._r.restore(text)
        self.restored += res.restored
        self.unknown.extend(res.unknown)
        return res.text
