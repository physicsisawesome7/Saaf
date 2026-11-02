"""Tenant runtime: ingestion and permission-aware, version-aware retrieval.

One ``Tenant`` per tenant pack. It owns the index for that tenant and talks to
the shared relational store and blob store. API replicas are stateless apart
from this in-process index, which is rebuilt from the store on start (vectors
come from the embedding cache, so a restart costs no model calls); with the
Qdrant backend there is nothing to rebuild.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import socket
import struct
import threading
import time
import zipfile
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from .access import AccessFilter, Directory, LocalAuthorizer
from .audit import AuditLog
from .chunking import render_rows, render_whole
from .config import Settings, TenantPack
from .guardrails import Guardrails
from .index import (
    Embedder,
    HashingEmbedder,
    HttpReranker,
    LexicalReranker,
    LocalIndex,
    OpenAICompatEmbedder,
    QdrantIndex,
    Reranker,
    VectorIndex,
    tokenize,
)
from .llm import Gateway
from .metadata import extract, front_matter
from .models import Access, Passage, Principal
from .parsers import parse, sniff
from .privacy import mask_table, mask_text
from .store import BlobStore, Store, memories, text_hash

MAX_FILE_MB = 100
ZIP_DEPTH = 2


class Tenant:
    def __init__(self, pack: TenantPack, store: Store, blobs: BlobStore, settings: Settings):
        self.pack = pack
        self.id = pack.id
        self.store = store
        self.blobs = blobs
        self.settings = settings
        self.audit = AuditLog(store, self.id)
        self.directory = Directory(pack.roles)
        self.authz = LocalAuthorizer()
        self.gw = Gateway(pack.config.models)
        self.guard = Guardrails(pack.guardrails, self.gw)
        self.embedder: Embedder = (
            OpenAICompatEmbedder(pack.config.models.embed)
            if pack.config.models.embed and pack.config.models.embed.base_url
            else HashingEmbedder()
        )
        self.reranker: Reranker = (
            HttpReranker(pack.config.models.rerank)
            if pack.config.models.rerank and pack.config.models.rerank.base_url
            else LexicalReranker(self._idf)
        )
        self.index: VectorIndex = (
            QdrantIndex(settings.qdrant_url or "http://localhost:6333", f"smriti_{self.id}", self.embedder.dim)
            if settings.vector_backend == "qdrant"
            else LocalIndex(self.embedder.dim)
        )
        self.generation = 0  # bumped on every ingest; invalidates the answer cache
        self._ingest_lock = threading.Lock()
        self._rebuild()

    # ------------------------------------------------------------------ helpers

    def _idf(self, term: str) -> float:
        if isinstance(self.index, LocalIndex):
            n = max(1, len(self.index.ids))
            df = len(self.index.postings.get(term, {}))
            return float(np.log(1 + (n - df + 0.5) / (df + 0.5)))
        return 1.0

    def _index_text(self, c: dict[str, Any]) -> str:
        body = c["text"] if self.pack.config.retrieval.index_pii else c["text_masked"]
        return f"{c['header']}\n{body}"

    def _payload(self, c: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "chunk_id": c["chunk_id"],
            "doc_id": c["doc_id"],
            "doc_type": doc["doc_type"],
            "access": doc["access"],
            "current": c.get("last_version") is None and doc["status"] == "current",
            "clause_id": c.get("clause_id"),
            "lang": c.get("lang", "en"),
        }

    def _embed(self, texts: list[str]) -> np.ndarray:
        hashes = [text_hash(t) for t in texts]
        cached = self.store.get_embeddings(self.embedder.name, hashes)
        missing = [i for i, h in enumerate(hashes) if h not in cached]
        out = np.zeros((len(texts), self.embedder.dim), dtype=np.float32)
        if missing:
            vecs = self.embedder.embed([texts[i] for i in missing])
            self.store.put_embeddings(
                self.embedder.name,
                {hashes[i]: vecs[j].astype(np.float32).tobytes() for j, i in enumerate(missing)},
                self.embedder.dim,
            )
            for j, i in enumerate(missing):
                out[i] = vecs[j]
        for i, h in enumerate(hashes):
            if h in cached:
                out[i] = np.frombuffer(cached[h], dtype=np.float32)
        return out

    def _rebuild(self) -> None:
        if not isinstance(self.index, LocalIndex):
            return
        rows = self.store.all_chunks(self.id)
        if not rows:
            return
        docs = {d["doc_id"]: d for d in self.store.list_documents(self.id)}
        rows = [r for r in rows if r["doc_id"] in docs and docs[r["doc_id"]]["status"] != "tombstoned"]
        texts = [self._index_text(r) for r in rows]
        vecs = self._embed(texts)
        self.index.upsert(
            [(r["chunk_id"], vecs[i], texts[i], self._payload(r, docs[r["doc_id"]])) for i, r in enumerate(rows)]
        )

    def principal(self, user_id: str) -> Principal:
        return self.directory.principal(user_id)

    # ------------------------------------------------------------------ ingestion

    def ingest(
        self,
        data: bytes,
        filename: str,
        *,
        actor: str,
        source: str | None = None,
        source_url: str | None = None,
        hints: dict[str, Any] | None = None,
        doc_id: str | None = None,
        legal_status: str | None = None,
        _depth: int = 0,
    ) -> dict[str, Any]:
        if len(data) > MAX_FILE_MB * 1024 * 1024:
            raise ValueError(f"{filename}: larger than {MAX_FILE_MB} MB")
        mime = sniff(data, filename)
        if mime == "application/zip":
            return self._ingest_zip(data, filename, actor=actor, source=source, hints=hints, depth=_depth)
        scan = scan_malware(data)
        if scan.get("infected"):
            self.audit.record(
                actor, "ingest_rejected", filename=filename, reason="malware", signature=scan.get("signature")
            )
            raise ValueError(f"{filename}: rejected by malware scan ({scan.get('signature')})")

        with self._ingest_lock:
            sha = hashlib.sha256(data).hexdigest()
            dup = self.store.version_by_sha(self.id, sha)
            if dup:
                return {"status": "duplicate", "doc_id": dup["doc_id"], "version": dup["version"]}

            fm = front_matter(data)
            merged: dict[str, Any] = {**(hints or {}), **fm}
            parsed = parse(data, filename)
            if parsed.parser == "email" and "correspondence" in self.pack.schemas:
                merged.setdefault("doc_type", "correspondence")
            title = str(merged.get("title") or parsed.title)
            meta = extract(parsed.text, title, self.pack.schemas, merged)
            # Only a declared reference names the document; a reference merely found in the
            # text (a letter quoting a tender number) must not turn it into a version of that tender.
            ref_declared = bool(merged.get("ref_no"))
            doc_id = (
                doc_id
                or merged.get("doc_id")
                or _derive_doc_id(source, source_url, meta.get("ref_no") if ref_declared else None, filename)
            )
            existing = self.store.get_document(self.id, doc_id)
            version = (existing["current_version"] + 1) if existing else 1

            access = Access.from_dict(merged.get("access") or (existing["access"] if existing else None))
            schema = self.pack.schemas.get(meta["doc_type"], {})
            name_cols = schema.get("pii_columns") or None

            def mask_rows(header: list[str], rows: list[list[str]]) -> list[list[str]]:
                kw = {"name_columns": name_cols} if name_cols else {}
                return mask_table(header, rows, (), **kw)[0]

            from .chunking import chunk_document

            chunks, tables = chunk_document(doc_id, parsed, meta, mask_rows=mask_rows)
            pii: set[str] = set(access.pii)
            for c in chunks:
                if c.kind in ("table", "table_rows"):
                    if c.text_masked != c.text:
                        pii.add("land_owner_name")
                    mt, cats = mask_text(c.text_masked)
                    c.text_masked = mt
                else:
                    c.text_masked, cats = mask_text(c.text)
                pii |= cats
            access.pii = sorted(pii)

            raw_key = self.blobs.put(data, Path(filename).suffix[:10])
            parse_key = self.blobs.put(
                json.dumps([asdict(b) for b in parsed.blocks], ensure_ascii=False).encode("utf-8"), ".json"
            )

            injection_blocks = sum(1 for c in chunks if self.guard.scan_passage(c.text))
            doc = {
                "doc_id": doc_id,
                "title": title,
                "doc_type": meta["doc_type"],
                "ref_no": meta.get("ref_no"),
                "doc_date": meta.get("doc_date"),
                "source": source or (existing or {}).get("source") or "upload",
                "source_url": source_url or (existing or {}).get("source_url"),
                "access": access.to_dict(),
                "status": "current" if not existing or existing["status"] != "superseded" else "superseded",
                "current_version": version,
                "meta": {
                    **((existing or {}).get("meta") or {}),
                    "aliases": list(merged.get("aliases") or ((existing or {}).get("meta") or {}).get("aliases") or []),
                    "effective_from": meta.get("effective_from"),
                    "ref_declared": ref_declared,
                    "lang": _majority([c.lang for c in chunks]) if chunks else "en",
                    "pages": parsed.pages,
                    "parser": parsed.parser,
                    "low_confidence": parsed.low_confidence,
                    "warnings": parsed.warnings,
                    "injection_blocks": injection_blocks,
                    "legal_status": legal_status or merged.get("legal_status") or "customer-owned",
                    "sha256": sha,
                },
            }
            self.store.upsert_document(self.id, doc)
            self.store.add_version(
                self.id,
                {
                    "doc_id": doc_id,
                    "version": version,
                    "sha256": sha,
                    "blob_key": raw_key,
                    "parse_key": parse_key,
                    "filename": filename,
                    "mime": parsed.mime,
                    "parser": parsed.parser,
                    "effective_from": meta.get("effective_from"),
                    "valid_until": meta.get("valid_until"),
                    "pages": parsed.pages,
                    "low_confidence": parsed.low_confidence,
                    "warnings": json.dumps(parsed.warnings),
                },
            )

            # incremental chunk update: only changed chunks are embedded
            old_ids = self.store.current_chunk_ids(self.id, doc_id)
            new_by_id = {c.chunk_id: c for c in chunks}
            added = [c for cid, c in new_by_id.items() if cid not in old_ids]
            removed = old_ids - set(new_by_id)
            self.store.close_chunks(self.id, removed, version - 1)
            rows = [
                {
                    "chunk_id": c.chunk_id,
                    "doc_id": doc_id,
                    "first_version": version,
                    "last_version": None,
                    "text": c.text,
                    "text_masked": c.text_masked,
                    "header": c.header,
                    "section_path": json.dumps(c.section_path, ensure_ascii=False),
                    "clause_id": c.clause_id,
                    "page": c.page,
                    "kind": c.kind,
                    "lang": c.lang,
                    "confidence": c.confidence,
                    "table_id": c.table_id,
                    "text_hash": text_hash(c.text),
                }
                for c in added
            ]
            self.store.insert_chunks(self.id, rows)
            for t in tables:
                self.store.put_table(self.id, {**t, "version": version})

            dict_rows = [r | {"section_path": json.loads(r["section_path"])} for r in rows]
            texts = [self._index_text(r) for r in dict_rows]
            if texts:
                vecs = self._embed(texts)
                self.index.upsert(
                    [(r["chunk_id"], vecs[i], texts[i], self._payload(r, doc)) for i, r in enumerate(dict_rows)]
                )
            if removed:
                self.index.set_payload(list(removed), {"current": False})
            kept = [cid for cid in new_by_id if cid in old_ids]
            if kept:
                self.index.set_payload(
                    kept, {"access": doc["access"], "doc_type": doc["doc_type"], "current": doc["status"] == "current"}
                )

            impact = self._apply_relations(doc_id, meta, actor)
            self.generation += 1

        self.audit.record(
            actor,
            "ingest",
            doc_id=doc_id,
            version=version,
            sha256=sha,
            source=doc["source"],
            chunks_added=len(added),
            chunks_retired=len(removed),
            chunks_unchanged=len(new_by_id) - len(added),
            doc_class=access.doc_class,
            pii=access.pii,
        )
        return {
            "status": "ingested" if version == 1 else "new_version",
            "doc_id": doc_id,
            "version": version,
            "title": title,
            "doc_type": meta["doc_type"],
            "ref_no": meta.get("ref_no"),
            "chunks_added": len(added),
            "chunks_retired": len(removed),
            "chunks_unchanged": len(new_by_id) - len(added),
            "warnings": parsed.warnings,
            "relations": meta["relations"],
            "impact": impact,
        }

    def _ingest_zip(
        self, data: bytes, filename: str, *, actor: str, source: str | None, hints: dict[str, Any] | None, depth: int
    ) -> dict[str, Any]:
        if depth >= ZIP_DEPTH:
            raise ValueError(f"{filename}: archive nesting deeper than {ZIP_DEPTH}")
        results = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                if info.flag_bits & 0x1:
                    raise ValueError(f"{filename}: encrypted archive; the owner must supply the key")
                if info.file_size > MAX_FILE_MB * 1024 * 1024:
                    continue
                inner = z.read(info)
                results.append(
                    self.ingest(inner, info.filename, actor=actor, source=source, hints=hints, _depth=depth + 1)
                )
        return {"status": "archive", "filename": filename, "members": results}

    def _apply_relations(self, doc_id: str, meta: dict[str, Any], actor: str) -> list[dict[str, Any]]:
        """Write supersession edges, retire superseded documents, and list what a
        modifying document touches (the circular impact analysis)."""
        effective = meta.get("effective_from") or meta.get("doc_date")
        for rel in meta.get("relations", []):
            dst = self.store.find_by_ref(self.id, rel["dst_ref"])
            if dst and dst["doc_id"] == doc_id:
                continue
            self.store.add_relation(
                self.id,
                {
                    "src_doc": doc_id,
                    "rel_type": rel["rel_type"],
                    "dst_doc": dst["doc_id"] if dst else None,
                    "dst_ref": rel["dst_ref"],
                    "clause_id": rel.get("clause_id"),
                    "effective_from": effective,
                    "evidence": rel.get("evidence"),
                },
            )
        self.store.resolve_relations(self.id)
        # supersession: a document superseded by one already in force stops being current
        today = date.today().isoformat()
        for r in self.store.all_relations(self.id):
            if r["rel_type"] == "supersedes" and r["dst_doc"] and (r["effective_from"] or "") <= today:
                d = self.store.get_document(self.id, r["dst_doc"])
                if d and d["status"] == "current":
                    self.store.set_doc_status(self.id, r["dst_doc"], "superseded")
                    self.index.set_payload_where(r["dst_doc"], {"current": False})
                    self._flag_memories(r["dst_doc"])
                    self.audit.record(actor, "superseded", doc_id=r["dst_doc"], by=r["src_doc"])
        return self.impact_of(doc_id)

    def _flag_memories(self, doc_id: str) -> None:
        for m in self.store.rows(memories, tenant=self.id):
            if doc_id in json.loads(m["provenance"] or "[]"):
                self.store.update_row(memories, {"id": m["id"]}, needs_revalidation=True)

    def impact_of(self, doc_id: str) -> list[dict[str, Any]]:
        rels = self.store.all_relations(self.id)
        out = []
        for r in rels:
            if r["src_doc"] != doc_id or r["rel_type"] not in ("modifies", "supersedes") or not r["dst_doc"]:
                continue
            for ref in rels:
                if ref["rel_type"] != "refers_to" or ref["dst_doc"] != r["dst_doc"] or ref["src_doc"] == doc_id:
                    continue
                if r["clause_id"] and ref["clause_id"] and not _clause_match(r["clause_id"], ref["clause_id"]):
                    continue
                d = self.store.get_document(self.id, ref["src_doc"])
                if d and d["status"] != "tombstoned":
                    out.append(
                        {
                            "doc_id": d["doc_id"],
                            "title": d["title"],
                            "doc_type": d["doc_type"],
                            "clause_id": ref["clause_id"],
                            "via": r["dst_doc"],
                            "change": r["rel_type"],
                            "access": d["access"],
                            "evidence": ref["evidence"],
                        }
                    )
        seen = set()
        uniq = []
        for o in out:
            k = (o["doc_id"], o["clause_id"])
            if k not in seen:
                seen.add(k)
                uniq.append(o)
        return uniq

    def tombstone(self, doc_id: str, actor: str, reason: str) -> None:
        self.store.set_doc_status(self.id, doc_id, "tombstoned")
        self.index.set_payload_where(
            doc_id,
            {
                "current": False,
                "access": {
                    "doc_class": "secret",
                    "divisions": [],
                    "projects": ["__tombstoned__"],
                    "groups": ["__tombstoned__"],
                    "pii": [],
                    "extra_rules": [],
                },
            },
        )
        self.generation += 1
        self.audit.record(actor, "tombstone", doc_id=doc_id, reason=reason)

    # ------------------------------------------------------------------ retrieval

    def expand_query(self, query: str) -> tuple[str, list[str], str]:
        """Glossary expansion (LOA -> letter of acceptance) and cross-language synonyms.

        Returns (text to search with, expansions, text to judge relevance with).
        Search uses every expansion; relevance uses the question plus
        abbreviation expansions, and synonyms only when they cross scripts
        (a Hindi question judged against English passages), so a Hindi synonym
        never dilutes an English question.
        """
        g = self.pack.glossary
        extra: list[str] = []
        focus: list[str] = []
        low = query.lower()
        hindi_q = bool(re.search(r"[ऀ-ॿ]", query))
        for abbr, full in (g.get("abbreviations") or {}).items():
            if re.search(rf"(?<![\w]){re.escape(abbr.lower())}(?![\w])", low):
                extra.append(str(full))
                focus.append(str(full))
        for term, syns in (g.get("synonyms") or {}).items():
            names = [term, *([syns] if isinstance(syns, str) else syns)]
            if any(re.search(rf"(?<![\wऀ-ॿ]){re.escape(n.lower())}", low) for n in names):
                new = [str(n) for n in names if n.lower() not in low]
                extra.extend(new)
                if hindi_q:  # a Hindi question is judged against English passages too
                    focus.extend(n for n in new if not re.search(r"[ऀ-ॿ]", n))
        searched = query + (" " + " ".join(extra) if extra else "")
        return searched, extra, query + (" " + " ".join(focus) if focus else "")

    def retrieve(
        self,
        p: Principal,
        query: str,
        *,
        as_of: str | None = None,
        include_superseded: bool = False,
        top_k: int | None = None,
        doc_ids: list[str] | None = None,
    ) -> tuple[list[Passage], dict[str, Any]]:
        t0 = time.perf_counter()
        rc = self.pack.config.retrieval
        top_k = top_k or rc.top_k
        expanded, extra, focus_text = self.expand_query(query)
        qtokens = tokenize(expanded)
        focus = tokenize(focus_text)
        qvec = self._embed_query(expanded)
        flt = AccessFilter(p)
        allow = flt.matches if not doc_ids else (lambda pl: flt.matches(pl) and pl["doc_id"] in doc_ids)
        current_only = as_of is None and not include_superseded
        t1 = time.perf_counter()
        hits = self.index.search(
            qvec,
            qtokens,
            allow,
            flt.to_qdrant() if isinstance(self.index, QdrantIndex) else None,
            rc.candidates,
            rc.rrf_k,
            current_only,
        )
        t2 = time.perf_counter()

        docs = self.store.documents_by_ids(self.id, [h.payload["doc_id"] for h in hits])
        allowed = self.authz.bulk_check(p, docs)  # second enforcement point
        dropped = sum(1 for h in hits if h.payload["doc_id"] not in allowed)
        hits = [h for h in hits if h.payload["doc_id"] in allowed]
        chunk_rows = self.store.get_chunks(self.id, [h.chunk_id for h in hits])

        kept: list[tuple[Any, dict[str, Any], str]] = []
        versions_cache: dict[str, list[dict[str, Any]]] = {}
        sup = self._superseded_by()
        overridden = self._overridden_amendments(as_of or date.today().isoformat())
        for h in hits:
            c = chunk_rows.get(h.chunk_id)
            if not c:
                continue
            d = docs[c["doc_id"]]
            status = "current"
            if as_of:
                vs = versions_cache.setdefault(d["doc_id"], self.store.get_versions(self.id, d["doc_id"]))
                in_force = [
                    v
                    for v in vs
                    if (v["effective_from"] or "0000") <= as_of and (not v["valid_until"] or v["valid_until"] > as_of)
                ]
                if not in_force:
                    continue
                v_star = max(v["version"] for v in in_force)
                if not (c["first_version"] <= v_star and (c["last_version"] is None or c["last_version"] >= v_star)):
                    continue
                by = sup.get(d["doc_id"])
                if by and (by[1] or "") <= as_of and not include_superseded:
                    continue
                status = "historic" if (v_star != d["current_version"] or d["status"] == "superseded") else "current"
            else:
                if c["last_version"] is not None:
                    if not include_superseded:
                        continue
                    status = "historic"
                if d["status"] == "superseded":
                    if not include_superseded:
                        continue
                    status = "superseded"
            if d["doc_id"] in overridden and status == "current":
                # an earlier slip whose every amendment has been replaced by a later one
                if not include_superseded:
                    continue
                status = "superseded"
            kept.append((h, c, status))

        # rerank the authorised, in-force candidates
        texts = [f"{c['header']}\n{c['text_masked']}" for _, c, _ in kept]
        scores = self.reranker.score(focus_text, focus, texts, [h.score for h, _, _ in kept]) if kept else []
        order = sorted(range(len(kept)), key=lambda i: scores[i], reverse=True)
        t3 = time.perf_counter()

        passages: list[Passage] = []
        used: set[str] = set()
        for i in order:
            if len(passages) >= top_k:
                break
            h, c, status = kept[i]
            if c["chunk_id"] in used:
                continue
            used.add(c["chunk_id"])
            passages.append(self._passage(p, len(passages) + 1, c, docs[c["doc_id"]], scores[i], status))
            # version rule: a clause comes with the latest amendment in force on the date asked
            if c.get("clause_id"):
                for amend in self._amendments(p, c, as_of or date.today().isoformat())[-1:]:
                    if amend[0]["chunk_id"] not in used and len(passages) < top_k + 4:
                        used.add(amend[0]["chunk_id"])
                        passages.append(
                            self._passage(
                                p, len(passages) + 1, amend[0], amend[1], scores[i], "amendment", note=amend[2]
                            )
                        )
        t4 = time.perf_counter()
        trace = {
            "query_expanded": expanded if extra else None,
            "glossary": extra,
            "candidates": len(hits) + dropped,
            "dropped_by_bulk_check": dropped,
            "after_version_rules": len(kept),
            "current_only": current_only,
            "as_of": as_of,
            "reranker": self.reranker.name,
            "embedder": self.embedder.name,
            "top_scores": [round(scores[i], 3) for i in order[:top_k]],
            "timings_ms": {
                "prepare": round((t1 - t0) * 1000, 1),
                "search": round((t2 - t1) * 1000, 1),
                "authorise_and_version": round((t3 - t2) * 1000, 1),
                "assemble": round((t4 - t3) * 1000, 1),
            },
            "qtokens": focus,
        }
        return passages, trace

    def _embed_query(self, q: str) -> np.ndarray:
        if isinstance(self.embedder, OpenAICompatEmbedder):
            return self.embedder.embed([q], query=True)[0]
        return self.embedder.embed([q])[0]

    def _overridden_amendments(self, when: str) -> set[str]:
        """Slips all of whose clause amendments were replaced by later slips in force on ``when``."""
        latest: dict[tuple[str, str], tuple[str, str]] = {}
        mods: dict[str, list[tuple[str, str]]] = {}
        for r in self.store.all_relations(self.id):
            if (
                r["rel_type"] != "modifies"
                or not r["dst_doc"]
                or not r["clause_id"]
                or (r["effective_from"] or "") > when
            ):
                continue
            key = (r["dst_doc"], r["clause_id"])
            mods.setdefault(r["src_doc"], []).append(key)
            if key not in latest or (r["effective_from"] or "") > latest[key][0]:
                latest[key] = (r["effective_from"] or "", r["src_doc"])
        return {src for src, keys in mods.items() if all(latest[k][1] != src for k in keys)}

    def _superseded_by(self) -> dict[str, tuple[str, str | None]]:
        return {
            r["dst_doc"]: (r["src_doc"], r["effective_from"])
            for r in self.store.all_relations(self.id)
            if r["rel_type"] == "supersedes" and r["dst_doc"]
        }

    def _amendments(
        self, p: Principal, c: dict[str, Any], when: str
    ) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
        out = []
        rels = [
            r
            for r in self.store.relations_for(self.id, c["doc_id"])
            if r["rel_type"] == "modifies"
            and r["dst_doc"] == c["doc_id"]
            and r["clause_id"]
            and _clause_match(r["clause_id"], c["clause_id"])
            and (r["effective_from"] or "") <= when
        ]
        if not rels:
            return out
        docs = self.store.documents_by_ids(self.id, [r["src_doc"] for r in rels])
        ok = self.authz.bulk_check(p, docs)
        for r in sorted(rels, key=lambda r: r["effective_from"] or ""):
            if r["src_doc"] not in ok:
                continue
            src_chunks = [x for x in self.store.doc_chunks(self.id, r["src_doc"]) if r["clause_id"] in x["text"]]
            if src_chunks:
                d = docs[r["src_doc"]]
                out.append((src_chunks[0], d, f"Amends clause {r['clause_id']} w.e.f. {r['effective_from']}"))
        return out

    def _passage(
        self,
        p: Principal,
        n: int,
        c: dict[str, Any],
        d: dict[str, Any],
        score: float,
        status: str,
        note: str | None = None,
    ) -> Passage:
        text, masked = self.render_for(p, c, d)
        return Passage(
            n=n,
            chunk_id=c["chunk_id"],
            doc_id=d["doc_id"],
            version=c["first_version"] if c["last_version"] is None else c["last_version"],
            title=d["title"],
            ref_no=d.get("ref_no"),
            doc_date=d.get("doc_date"),
            doc_type=d["doc_type"],
            clause_id=c.get("clause_id"),
            section=" > ".join(c["section_path"][-3:]),
            page=c.get("page") or 1,
            text=text,
            score=round(float(score), 3),
            status=status,
            doc_class=d["access"]["doc_class"],
            confidence=c.get("confidence", 1.0),
            masked=masked,
            note=note or ("low-confidence parse" if (c.get("confidence") or 1) < 0.6 else None),
            injection_flag=self.guard.scan_passage(c["text"]),
        )

    def render_for(self, p: Principal, c: dict[str, Any], d: dict[str, Any]) -> tuple[str, bool]:
        """Field-level masking by role: the document is visible, its PII may not be."""
        pii = set(d["access"].get("pii") or [])
        if not pii:
            return c["text"], False
        if not p.unmask:
            return c["text_masked"], c["text_masked"] != c["text"]
        if pii <= {u.lower() for u in p.unmask}:
            return c["text"], False
        if c.get("table_id"):
            t = self.store.get_table(self.id, c["table_id"])
            if t:
                header = t["columns"]
                schema = self.pack.schemas.get(d["doc_type"], {})
                kw = {"name_columns": schema["pii_columns"]} if schema.get("pii_columns") else {}
                body, _ = mask_table(header, t["rows"], p.unmask, **kw)
                if c["kind"] == "table":
                    return render_whole(header, body), True
                m = re.search(r"Rows (\d+)-(\d+)", c["section_path"][-1] if c["section_path"] else "")
                if m:
                    return render_rows(header, body[int(m.group(1)) - 1 : int(m.group(2))]), True
        txt, cats = mask_text(c["text"], p.unmask)
        return txt, bool(cats)


def _clause_match(a: str, b: str) -> bool:
    return a == b or b.startswith(a + ".") or a.startswith(b + ".")


def _majority(xs: list[str]) -> str:
    return max(set(xs), key=xs.count) if xs else "en"


def _derive_doc_id(source: str | None, url: str | None, ref: str | None, filename: str) -> str:
    if url:
        from .watch import normalise_url

        return "url-" + text_hash(normalise_url(url))[:16]
    if ref:
        return "ref-" + re.sub(r"[^a-z0-9]+", "-", ref.lower()).strip("-")[:80]
    stem = Path(filename).stem
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:80] or "doc-" + text_hash(filename)[:12]


def scan_malware(data: bytes) -> dict[str, Any]:
    """ClamAV INSTREAM scan when SMRITI_CLAMD=host:port is set; otherwise a no-op
    that says so (recorded in the audit trail by the caller's context)."""
    import os

    target = os.environ.get("SMRITI_CLAMD")
    if not target:
        return {"scanned": False}
    host, _, port = target.partition(":")
    try:
        with socket.create_connection((host, int(port or 3310)), timeout=10) as s:
            s.sendall(b"zINSTREAM\0")
            for i in range(0, len(data), 8192):
                part = data[i : i + 8192]
                s.sendall(struct.pack("!L", len(part)) + part)
            s.sendall(struct.pack("!L", 0))
            reply = s.recv(4096).decode("utf-8", "replace").strip("\0\n ")
    except OSError as e:
        return {"scanned": False, "error": str(e)}
    infected = reply.endswith("FOUND")
    return {
        "scanned": True,
        "infected": infected,
        "signature": reply.split(":", 1)[-1].replace("FOUND", "").strip() if infected else None,
    }
