"""Domain types shared across the pipeline.

Plain dataclasses so the core has no framework dependency; the API layer
converts them to JSON with ``asdict``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

# Sensitivity classes from least to most restricted. A role's clearance and a
# memory's "strictest source" rule both compare by position in this list.
DOC_CLASSES = ["public", "internal", "confidential", "secret"]


def class_rank(doc_class: str) -> int:
    try:
        return DOC_CLASSES.index(doc_class)
    except ValueError:
        return len(DOC_CLASSES)  # unknown classes are treated as the most restricted


@dataclass
class Block:
    """One unit of the canonical parse: every parser emits these."""

    kind: str  # heading | paragraph | table | list | figure
    text: str
    page: int = 1
    order: int = 0
    heading_path: list[str] = field(default_factory=list)
    lang: str = "en"
    confidence: float = 1.0
    bbox: list[float] | None = None
    rows: list[list[str]] | None = None  # tables keep their cells


@dataclass
class ParsedDocument:
    title: str
    blocks: list[Block]
    mime: str
    parser: str
    pages: int = 1
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)

    @property
    def low_confidence(self) -> bool:
        return any(b.confidence < 0.6 for b in self.blocks)


@dataclass
class Access:
    """Access attributes on a document. Chunks inherit them; never set per chunk."""

    doc_class: str = "internal"
    divisions: list[str] = field(default_factory=lambda: ["*"])
    projects: list[str] = field(default_factory=list)  # empty means not project-restricted
    groups: list[str] = field(default_factory=list)  # need-to-know groups; empty means none required
    pii: list[str] = field(default_factory=list)  # PII categories present, e.g. land_owner_name
    extra_rules: list[dict[str, Any]] = field(default_factory=list)  # ANDed rules (derived memories)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_class": self.doc_class,
            "divisions": self.divisions,
            "projects": self.projects,
            "groups": self.groups,
            "pii": self.pii,
            "extra_rules": self.extra_rules,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Access:
        d = d or {}
        return cls(
            doc_class=d.get("doc_class", "internal"),
            divisions=list(d.get("divisions") or ["*"]),
            projects=list(d.get("projects") or []),
            groups=list(d.get("groups") or []),
            pii=list(d.get("pii") or []),
            extra_rules=list(d.get("extra_rules") or []),
        )


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str  # as written in the source
    text_masked: str  # PII-masked rendition, served to anyone without unmask rights
    header: str  # context header embedded with the chunk
    section_path: list[str] = field(default_factory=list)
    clause_id: str | None = None
    page: int = 1
    kind: str = "paragraph"
    lang: str = "en"
    confidence: float = 1.0
    table_id: str | None = None

    @staticmethod
    def make_id(doc_id: str, section_path: list[str], text: str) -> str:
        h = hashlib.sha256(f"{doc_id}|{'/'.join(section_path)}|{text}".encode()).hexdigest()
        return h[:24]


@dataclass
class Principal:
    """The person asking, resolved from SSO claims or the demo directory."""

    user_id: str
    name: str
    roles: list[str]
    grants: set[str]
    divisions: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    clearance: str = "internal"
    unmask: set[str] = field(default_factory=set)
    role_scopes: list[dict[str, Any]] = field(default_factory=list)  # one resolved scope per role with "view"

    def can(self, grant: str) -> bool:
        return grant in self.grants

    @property
    def access_key(self) -> str:
        """Hash of everything that decides what this person may read.

        Caches and memories are keyed by it, so one person's answer is never
        served to someone with different rights.
        """
        parts = [
            repr(sorted(self.role_scopes, key=repr)),
            self.clearance,
            ",".join(sorted(self.unmask)),
            ",".join(sorted(self.groups)),  # includes user:<id>, so personal memories never cross users
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


@dataclass
class Passage:
    """A retrieved, authorised, possibly masked chunk ready for the prompt."""

    n: int
    chunk_id: str
    doc_id: str
    version: int
    title: str
    ref_no: str | None
    doc_date: str | None
    doc_type: str
    clause_id: str | None
    section: str
    page: int
    text: str
    score: float
    status: str  # current | superseded | amendment | historic
    doc_class: str
    confidence: float = 1.0
    masked: bool = False
    note: str | None = None
    injection_flag: bool = False
