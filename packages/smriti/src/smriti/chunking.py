"""Chunking matched to how these documents are written.

* Contract conditions and codes: one chunk per numbered clause or sub-clause,
  clause id kept in metadata so "what does clause 16.1 say" is an exact match.
* Circulars and letters: paragraph groups up to the size budget.
* Tables: the whole table as one unit plus row-group chunks that repeat the
  header; the structured copy goes to the table store for exact maths.

Every chunk is embedded with a short context header (title, reference, date,
section path). That header is why a bare sentence such as "the period shall
be 30 days" is still found under the right document.

Chunk ids hash (doc id, section path, text), so re-ingesting a changed
document re-embeds only the chunks that actually changed.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any

from .models import Block, Chunk, ParsedDocument
from .parsers import CLAUSE_HEAD

MAX_WORDS = 380
ROWS_PER_CHUNK = 12


def _words(s: str) -> int:
    return len(s.split())


def header_for(title: str, ref_no: str | None, doc_date: str | None, path: list[str]) -> str:
    parts = [title]
    if ref_no:
        parts.append(ref_no)
    if doc_date:
        parts.append(doc_date)
    if path:
        parts.append(" > ".join(path[-3:]))
    return " | ".join(parts)


def chunk_document(
    doc_id: str,
    parsed: ParsedDocument,
    meta: dict[str, Any],
    mask_rows: Callable[[list[str], list[list[str]]], list[list[str]]] | None = None,
) -> tuple[list[Chunk], list[dict[str, Any]]]:
    """Returns (chunks, tables). Table chunks get their masked rendition from
    ``mask_rows`` (column-aware); text chunks are masked by the ingest pipeline."""
    title = parsed.title
    out: list[Chunk] = []
    tables: list[dict[str, Any]] = []

    unit: list[Block] = []
    unit_clause: str | None = None

    def emit(blocks: list[Block], clause: str | None) -> None:
        if not blocks:
            return
        text = "\n".join(b.text for b in blocks).strip()
        if not text:
            return
        path = blocks[0].heading_path
        sec = [*path, f"Clause {clause}"] if clause else list(path)
        for piece in _split(text):
            out.append(
                Chunk(
                    chunk_id=Chunk.make_id(doc_id, sec, piece),
                    doc_id=doc_id,
                    text=piece,
                    text_masked=piece,
                    header=header_for(title, meta.get("ref_no"), meta.get("doc_date"), sec),
                    section_path=sec,
                    clause_id=clause,
                    page=blocks[0].page,
                    kind=blocks[0].kind if len(blocks) == 1 else "paragraph",
                    lang=blocks[0].lang,
                    confidence=min(b.confidence for b in blocks),
                )
            )

    for b in parsed.blocks:
        if b.kind == "heading":
            emit(unit, unit_clause)
            unit, unit_clause = [], None
            m = CLAUSE_HEAD.match(b.text)
            if m:  # headings like "16. Performance Guarantee" open clause 16
                unit_clause = m.group(1)
                unit = [b]
            continue
        if b.kind == "table" and b.rows:
            emit(unit, unit_clause)
            unit, unit_clause = [], None
            tables.append(_table(doc_id, b, title, meta, out, mask_rows))
            continue
        m = CLAUSE_HEAD.match(b.text) if b.kind == "paragraph" else None
        if m:
            carry = unit if unit and all(x.kind == "heading" for x in unit) else []
            if not carry:
                emit(unit, unit_clause)
            unit, unit_clause = [*carry, b], m.group(1)
            continue
        unit.append(b)
        if _words(" ".join(x.text for x in unit)) > MAX_WORDS:
            emit(unit, unit_clause)
            unit = []
    emit(unit, unit_clause)
    return out, tables


def _split(text: str) -> list[str]:
    if _words(text) <= MAX_WORDS * 1.3:
        return [text]
    sents = re.split(r"(?<=[.;।?])\s+", text)
    pieces, cur = [], []
    for s in sents:
        cur.append(s)
        if _words(" ".join(cur)) >= MAX_WORDS:
            pieces.append(" ".join(cur))
            cur = cur[-1:]  # one sentence of overlap keeps context across the cut
    if cur and (not pieces or " ".join(cur) != pieces[-1].split(" ", 1)[-1]):
        pieces.append(" ".join(cur))
    return pieces


def render_rows(header: list[str], group: list[list[str]]) -> str:
    return "\n".join("; ".join(f"{h}: {v}" for h, v in zip(header, r, strict=False) if v) for r in group)


def render_whole(header: list[str], body: list[list[str]]) -> str:
    rows = [header, *body[: ROWS_PER_CHUNK * 3]]
    return "\n".join(
        ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + ["| " + " | ".join(r) + " |" for r in rows[1:]]
    )


def _table(
    doc_id: str,
    b: Block,
    title: str,
    meta: dict[str, Any],
    out: list[Chunk],
    mask_rows: Callable[[list[str], list[list[str]]], list[list[str]]] | None,
) -> dict[str, Any]:
    rows = b.rows or []
    header, body = rows[0], rows[1:]
    mbody = mask_rows(header, body) if mask_rows else body
    table_id = hashlib.sha256(f"{doc_id}|{'/'.join(b.heading_path)}|{b.order}".encode()).hexdigest()[:16]
    sec = [*b.heading_path, "Table"] if b.heading_path else ["Table"]
    hdr = header_for(title, meta.get("ref_no"), meta.get("doc_date"), sec)
    whole, whole_m = render_whole(header, body), render_whole(header, mbody)
    out.append(
        Chunk(
            Chunk.make_id(doc_id, sec, whole),
            doc_id,
            whole,
            whole_m,
            hdr,
            sec,
            None,
            b.page,
            "table",
            b.lang,
            b.confidence,
            table_id,
        )
    )
    if len(body) > 3:
        for i in range(0, len(body), ROWS_PER_CHUNK):
            group, mgroup = body[i : i + ROWS_PER_CHUNK], mbody[i : i + ROWS_PER_CHUNK]
            text = render_rows(header, group)
            rsec = [*sec, f"Rows {i + 1}-{i + len(group)}"]
            out.append(
                Chunk(
                    Chunk.make_id(doc_id, rsec, text),
                    doc_id,
                    text,
                    render_rows(header, mgroup),
                    hdr,
                    rsec,
                    None,
                    b.page,
                    "table_rows",
                    b.lang,
                    b.confidence,
                    table_id,
                )
            )
    return {
        "table_id": table_id,
        "doc_id": doc_id,
        "name": " > ".join(b.heading_path) or title,
        "columns": header,
        "rows": body,
    }
