"""Policy-as-code: which action applies to a finding, per entity, destination
and role.

Actions
    mask   replace with a reversible token (restorable from the vault)
    hash   replace with a keyed, irreversible hash token
    block  refuse the whole request
    warn   leave the text unchanged but report the finding
    allow  do nothing

Modes
    enforce  apply actions
    shadow   observe only: report what *would* happen, change nothing

Resolution order: first matching ``[[rules]]`` entry, then the per-entity
setting, then ``default_action``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Action = Literal["mask", "hash", "block", "warn", "allow"]
Mode = Literal["enforce", "shadow"]
TokenStyle = Literal["label", "fake", "hmac"]
UnknownTokenPolicy = Literal["leave", "strip", "flag"]

ACTIONS: frozenset[str] = frozenset({"mask", "hash", "block", "warn", "allow"})


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    action: Action
    entities: tuple[str, ...] = ("*",)
    destinations: tuple[str, ...] = ("*",)
    roles: tuple[str, ...] = ("*",)

    def matches(self, entity: str, destination: str | None, role: str | None) -> bool:
        return (
            _match_any(self.entities, entity)
            and _match_any(self.destinations, destination or "")
            and _match_any(self.roles, role or "")
        )


def _match_any(patterns: Sequence[str], value: str) -> bool:
    return any(p == "*" or fnmatch.fnmatchcase(value, p) for p in patterns)


@dataclass(frozen=True)
class EntityPolicy:
    action: Action | None = None
    threshold: float | None = None


@dataclass(frozen=True)
class Policy:
    id: str = "default"
    mode: Mode = "enforce"
    threshold: float = 0.5
    default_action: Action = "mask"
    token_style: TokenStyle = "label"
    on_unknown_token: UnknownTokenPolicy = "leave"
    entities: Mapping[str, EntityPolicy] = field(default_factory=dict)
    rules: tuple[Rule, ...] = ()
    enabled_entities: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("enforce", "shadow"):
            raise PolicyError(f"mode must be 'enforce' or 'shadow', got {self.mode!r}")
        if self.default_action not in ACTIONS:
            raise PolicyError(f"unknown default_action {self.default_action!r}")
        if self.token_style not in ("label", "fake", "hmac"):
            raise PolicyError(f"unknown token_style {self.token_style!r}")
        if self.on_unknown_token not in ("leave", "strip", "flag"):
            raise PolicyError(f"unknown on_unknown_token {self.on_unknown_token!r}")
        for name, ep in self.entities.items():
            if ep.action is not None and ep.action not in ACTIONS:
                raise PolicyError(f"entities.{name}: unknown action {ep.action!r}")
        for r in self.rules:
            if r.action not in ACTIONS:
                raise PolicyError(f"rule {r}: unknown action {r.action!r}")

    @property
    def shadow(self) -> bool:
        return self.mode == "shadow"

    def threshold_for(self, entity: str) -> float:
        ep = self.entities.get(entity)
        return ep.threshold if ep and ep.threshold is not None else self.threshold

    def decide(self, entity: str, *, destination: str | None = None, role: str | None = None) -> Action:
        for rule in self.rules:
            if rule.matches(entity, destination, role):
                return rule.action
        ep = self.entities.get(entity)
        if ep and ep.action:
            return ep.action
        return self.default_action

    @property
    def fingerprint(self) -> str:
        """Stable short hash of the effective policy, recorded in audit logs."""
        blob = json.dumps(self.to_dict(), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": {
                "id": self.id,
                "mode": self.mode,
                "threshold": self.threshold,
                "default_action": self.default_action,
                "token_style": self.token_style,
                "on_unknown_token": self.on_unknown_token,
                **({"enabled_entities": list(self.enabled_entities)} if self.enabled_entities else {}),
            },
            "entities": {
                k: {kk: vv for kk, vv in (("action", v.action), ("threshold", v.threshold)) if vv is not None}
                for k, v in sorted(self.entities.items())
            },
            "rules": [
                {
                    "action": r.action,
                    "entities": list(r.entities),
                    "destinations": list(r.destinations),
                    "roles": list(r.roles),
                }
                for r in self.rules
            ],
        }

    # -- loading ----------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Policy:
        top = dict(data.get("policy", {}))
        enabled = top.pop("enabled_entities", None)
        known = {"id", "mode", "threshold", "default_action", "token_style", "on_unknown_token"}
        extra = set(top) - known
        if extra:
            raise PolicyError(f"unknown [policy] keys: {sorted(extra)}")
        entities = {
            name: EntityPolicy(action=cfg.get("action"), threshold=cfg.get("threshold"))
            for name, cfg in data.get("entities", {}).items()
        }
        rules = tuple(
            Rule(
                action=r["action"],
                entities=tuple(r.get("entities", ["*"])),
                destinations=tuple(r.get("destinations", ["*"])),
                roles=tuple(r.get("roles", ["*"])),
            )
            for r in data.get("rules", [])
        )
        return cls(**top, entities=entities, rules=rules, enabled_entities=tuple(enabled) if enabled else None)

    @classmethod
    def load(cls, path: str | Path) -> Policy:
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if p.suffix == ".toml":
            return cls.from_dict(tomllib.loads(text))
        if p.suffix == ".json":
            return cls.from_dict(json.loads(text))
        raise PolicyError(f"unsupported policy format {p.suffix!r} (use .toml or .json)")
