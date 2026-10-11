"""Load and compile the declarative detector spec (``spec/entities.json``).

The canonical spec lives at the repository root in ``spec/`` and is copied into
``saaf/_data/`` by ``scripts/sync_spec.py`` so the wheel is self-contained. CI
fails if the copies drift.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from saaf.validators import get_validator


@dataclass(frozen=True)
class Pattern:
    regex: re.Pattern[str]
    group: int = 0


@dataclass(frozen=True)
class OcrSpec:
    regex: re.Pattern[str]
    shape: str
    min_digits: int
    score: float


@dataclass(frozen=True)
class EntitySpec:
    id: str
    label: str
    phase: str
    severity: str
    priority: int
    canonical: str
    patterns: tuple[Pattern, ...]
    validator: Callable[[str], bool] | None
    validator_name: str | None
    on_invalid: str
    base_score: float
    validated_score: float
    requires_context: bool
    context: tuple[str, ...]
    context_boost: float
    negative_context: tuple[str, ...]
    negative_penalty: float
    ocr: OcrSpec | None
    fake: str | None


@dataclass(frozen=True)
class Spec:
    version: str
    context_window: int
    threshold: float
    entities: tuple[EntitySpec, ...]
    by_id: dict[str, EntitySpec] = field(repr=False)

    def entity(self, entity_id: str) -> EntitySpec:
        return self.by_id[entity_id]


def _compile(pattern: str, flags: str = "") -> re.Pattern[str]:
    f = re.ASCII
    if "i" in flags:
        f |= re.IGNORECASE
    return re.compile(pattern, f)


def canonicalize(kind: str, text: str) -> str:
    if kind == "digits":
        return "".join(ch for ch in text if "0" <= ch <= "9")
    if kind == "alnum_upper":
        return "".join(ch for ch in text if ch.isascii() and ch.isalnum()).upper()
    if kind == "lower":
        return text.strip().lower()
    return text.strip()


def _resolve_set(value: Any, sets: dict[str, list[str]]) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        if not value.startswith("@"):
            raise ValueError(f"context set reference must start with '@': {value!r}")
        return tuple(sets[value[1:]])
    return tuple(value)


def parse_spec(raw: dict[str, Any]) -> Spec:
    defaults = raw.get("defaults", {})
    sets = raw.get("context_sets", {})
    entities: list[EntitySpec] = []
    for e in raw["entities"]:
        ocr = None
        if "ocr" in e:
            o = e["ocr"]
            ocr = OcrSpec(_compile(o["pattern"], o.get("flags", "")), o["shape"], o.get("min_digits", 0), o["score"])
        vname = e.get("validator")
        entities.append(
            EntitySpec(
                id=e["id"],
                label=e.get("label", e["id"]),
                phase=e.get("phase", "P0"),
                severity=e.get("severity", "medium"),
                priority=e.get("priority", 50),
                canonical=e.get("canonical", "strip"),
                patterns=tuple(
                    Pattern(_compile(p["pattern"], p.get("flags", "")), p.get("group", 0)) for p in e["patterns"]
                ),
                validator=get_validator(vname) if vname else None,
                validator_name=vname,
                on_invalid=e.get("on_invalid", "drop"),
                base_score=e.get("base_score", 0.0),
                validated_score=e.get("validated_score", e.get("base_score", 0.0)),
                requires_context=e.get("requires_context", False),
                context=tuple(k.lower() for k in e.get("context", [])),
                context_boost=e.get("context_boost", 0.0),
                negative_context=tuple(k.lower() for k in _resolve_set(e.get("negative_context"), sets)),
                negative_penalty=e.get("negative_penalty", 0.0),
                ocr=ocr,
                fake=e.get("fake"),
            )
        )
    by_id = {e.id: e for e in entities}
    if len(by_id) != len(entities):
        raise ValueError("duplicate entity ids in spec")
    return Spec(
        version=raw.get("spec_version", "0"),
        context_window=defaults.get("context_window", 50),
        threshold=defaults.get("threshold", 0.5),
        entities=tuple(entities),
        by_id=by_id,
    )


def load_spec(path: str | Path | None = None) -> Spec:
    """Load a spec file, or the bundled default when ``path`` is None."""
    if path is None:
        return default_spec()
    return parse_spec(json.loads(Path(path).read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def default_spec() -> Spec:
    data = resources.files("saaf").joinpath("_data/entities.json").read_text(encoding="utf-8")
    return parse_spec(json.loads(data))
