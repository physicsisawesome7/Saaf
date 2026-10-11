"""The :class:`Saaf` session: detect -> apply policy -> tokenize -> restore."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from saaf.audit import AuditLogger
from saaf.crossturn import CrossTurnTracker
from saaf.detect import Detector, Finding, resolve_overlaps
from saaf.policy import Action, Policy
from saaf.restore import Restorer, RestoreResult
from saaf.spec import canonicalize
from saaf.stream import StreamRestorer
from saaf.tokens import FAKERS, hash_token, hmac_token, label_token
from saaf.vault import InMemoryVault, Vault


class SaafBlocked(RuntimeError):
    """Raised by :meth:`Saaf.mask` with ``raise_on_block=True``."""

    def __init__(self, entities: list[str]):
        super().__init__(f"blocked by policy: {', '.join(sorted(set(entities)))}")
        self.entities = entities


@dataclass(frozen=True)
class Applied:
    finding: Finding
    action: Action
    token: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = self.finding.to_dict()
        d["action"] = self.action
        if self.token:
            d["token"] = self.token
        return d


@dataclass
class MaskResult:
    text: str
    original_text: str = field(repr=False)
    applied: list[Applied] = field(default_factory=list)
    blocked: bool = False
    shadow: bool = False
    prior_leak: bool = False

    @property
    def findings(self) -> list[Finding]:
        return [a.finding for a in self.applied]

    @property
    def tokens(self) -> list[str]:
        return [a.token for a in self.applied if a.token and a.action == "mask"]

    @property
    def changed(self) -> bool:
        return self.text != self.original_text

    @property
    def entity_counts(self) -> dict[str, int]:
        return dict(Counter(a.finding.entity for a in self.applied))

    def summary(self) -> dict[str, Any]:
        """Types and counts only -- safe to log."""
        return {
            "entity_counts": self.entity_counts,
            "action_counts": dict(Counter(a.action for a in self.applied)),
            "blocked": self.blocked,
            "shadow": self.shadow,
            "prior_leak": self.prior_leak,
        }


class Saaf:
    """One conversation (or request) worth of masking state.

    The detector is stateless and can be shared across sessions; the vault
    holds this session's token mapping.

    >>> v = Saaf()
    >>> r = v.mask("PAN ABCPE1234F")
    >>> r.text
    'PAN [PAN_1]'
    >>> v.restore("Your PAN is [PAN_1].").text
    'Your PAN is ABCPE1234F.'
    """

    def __init__(
        self,
        policy: Policy | None = None,
        *,
        detector: Detector | None = None,
        vault: Vault | None = None,
        hmac_key: bytes | None = None,
        audit: AuditLogger | None = None,
        cross_turn: bool = False,
    ):
        self.policy = policy or Policy()
        self.detector = detector or Detector(entities=self.policy.enabled_entities)
        self.vault = vault if vault is not None else InMemoryVault()
        self._key = hmac_key or os.urandom(32)
        self.audit = audit
        self._cross = CrossTurnTracker() if cross_turn else None
        self._restorer = Restorer(self.vault, self.policy.on_unknown_token)
        self._min_threshold = min(
            [self.policy.threshold] + [ep.threshold for ep in self.policy.entities.values() if ep.threshold is not None]
        )

    # -- detection --------------------------------------------------------

    def scan(self, text: str) -> list[Finding]:
        found = self.detector.scan(text, threshold=self._min_threshold)
        return [f for f in found if f.score >= self.policy.threshold_for(f.entity)]

    # -- masking ----------------------------------------------------------

    def _token_for(self, f: Finding) -> str:
        existing = self.vault.lookup(f.entity, f.canonical)
        if existing is not None:
            return existing
        style = self.policy.token_style
        token: str | None = None
        if style == "fake":
            fake_kind = self.detector.spec.by_id[f.entity].fake if f.entity in self.detector.spec.by_id else None
            if fake_kind in FAKERS:
                token = FAKERS[fake_kind](f.text)
        if token is None and style == "hmac":
            token = hmac_token(self._key, f.entity, f.canonical)
        if token is None:
            token = label_token(f.entity, self.vault.next_index(f.entity))
        self.vault.store(token, f.entity, f.canonical, f.text)
        return token

    def mask(
        self,
        text: str,
        *,
        destination: str | None = None,
        role: str | None = None,
        raise_on_block: bool = False,
    ) -> MaskResult:
        findings = self.scan(text)
        prior_leak = False
        if self._cross is not None:
            findings, prior_leak = self._merge_cross_turn(text, findings)

        shadow = self.policy.shadow
        applied: list[Applied] = []
        replacements: list[tuple[int, int, str]] = []
        for f in findings:
            action = self.policy.decide(f.entity, destination=destination, role=role)
            token = None
            if action == "mask":
                token = self._token_for(f) if not shadow else None
            elif action == "hash":
                token = hash_token(self._key, f.entity, f.canonical)
            applied.append(Applied(f, action, token))
            if not shadow and token is not None:
                replacements.append((f.start, f.end, token))

        blocked = not shadow and any(a.action == "block" for a in applied)
        out = text
        if not blocked:
            for start, end, token in sorted(replacements, reverse=True):
                out = out[:start] + token + out[end:]

        result = MaskResult(out, text, applied, blocked=blocked, shadow=shadow, prior_leak=prior_leak)
        if self.audit is not None:
            self.audit.record(
                "mask",
                entities=[a.finding.entity for a in applied],
                actions=[a.action for a in applied],
                mode=self.policy.mode,
                policy=self.policy.fingerprint,
                destination=destination,
                blocked=blocked,
            )
        if blocked and raise_on_block:
            raise SaafBlocked([a.finding.entity for a in applied if a.action == "block"])
        return result

    def _merge_cross_turn(self, text: str, findings: list[Finding]) -> tuple[list[Finding], bool]:
        assert self._cross is not None
        extra: list[Finding] = []
        prior = False
        for hit in self._cross.check(text):
            prior = prior or hit.prior_leak
            for s, e in hit.spans:
                extra.append(
                    Finding(
                        "AADHAAR",
                        s,
                        e,
                        text[s:e],
                        0.7,
                        canonicalize("digits", text[s:e]),
                        "high",
                        validated=True,
                        detector="cross_turn",
                        priority=90,
                    )
                )
        if not extra:
            return findings, prior
        return resolve_overlaps(findings + extra), prior

    def mask_messages(self, messages: list[dict[str, Any]], **kw: Any) -> tuple[list[dict[str, Any]], list[MaskResult]]:
        """Mask OpenAI/Anthropic-style ``messages``; content may be a string or
        a list of ``{"type": "text", "text": ...}`` parts."""
        results: list[MaskResult] = []
        out: list[dict[str, Any]] = []
        for msg in messages:
            m = dict(msg)
            content = m.get("content")
            if isinstance(content, str):
                r = self.mask(content, **kw)
                results.append(r)
                m["content"] = r.text
            elif isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        r = self.mask(part["text"], **kw)
                        results.append(r)
                        part = {**part, "text": r.text}
                    parts.append(part)
                m["content"] = parts
            out.append(m)
        return out, results

    def mask_json(self, value: Any, *, fields: Iterable[str] | None = None, **kw: Any) -> Any:
        """Field-aware masking for JSON-like data. With ``fields``, only string
        values under those keys are scanned; otherwise every string is."""
        wanted = set(fields) if fields is not None else None

        def walk(v: Any, key: str | None) -> Any:
            if isinstance(v, str):
                if wanted is None or key in wanted:
                    return self.mask(v, **kw).text
                return v
            if isinstance(v, list):
                return [walk(x, key) for x in v]
            if isinstance(v, dict):
                return {k: walk(x, k) for k, x in v.items()}
            return v

        return walk(value, None)

    # -- restore ----------------------------------------------------------

    def restore(self, text: str, *, expected: list[str] | None = None) -> RestoreResult:
        return self._restorer.restore(text, expected=expected)

    def restore_json(self, value: Any) -> Any:
        return self._restorer.restore_json(value)

    def stream_restorer(self) -> StreamRestorer:
        return StreamRestorer(self._restorer)
