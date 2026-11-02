"""Relational store and raw blob store.

SQLAlchemy Core keeps one code path for SQLite (laptop pilots, tests) and
PostgreSQL (production, with CloudNativePG or Patroni for HA). Every row
carries the tenant id, which is what row-level security keys on in the shared
multi-tenant topology.

Raw files are content-addressed and immutable: re-parsing with a better parser
never needs a re-crawl.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    and_,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

md = MetaData()

documents = Table(
    "documents",
    md,
    Column("tenant", String(64), primary_key=True),
    Column("doc_id", String(128), primary_key=True),
    Column("title", Text, nullable=False),
    Column("doc_type", String(64), nullable=False, default="document"),
    Column("ref_no", String(256)),
    Column("doc_date", String(32)),
    Column("source", String(128)),
    Column("source_url", Text),
    Column("access", Text, nullable=False),
    Column("status", String(16), nullable=False, default="current"),
    Column("current_version", Integer, nullable=False, default=1),
    Column("meta", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)

versions = Table(
    "versions",
    md,
    Column("tenant", String(64), primary_key=True),
    Column("doc_id", String(128), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("sha256", String(64), nullable=False),
    Column("blob_key", Text, nullable=False),
    Column("parse_key", Text),
    Column("filename", Text),
    Column("mime", String(128)),
    Column("parser", String(64)),
    Column("effective_from", String(32)),
    Column("valid_until", String(32)),
    Column("ingested_at", Float, nullable=False),
    Column("pages", Integer, default=1),
    Column("low_confidence", Boolean, default=False),
    Column("warnings", Text, default="[]"),
)

chunks = Table(
    "chunks",
    md,
    Column("tenant", String(64), primary_key=True),
    Column("chunk_id", String(32), primary_key=True),
    Column("doc_id", String(128), nullable=False, index=True),
    Column("first_version", Integer, nullable=False),
    Column("last_version", Integer),  # null while the chunk is in the current version
    Column("text", Text, nullable=False),
    Column("text_masked", Text, nullable=False),
    Column("header", Text, nullable=False),
    Column("section_path", Text, nullable=False, default="[]"),
    Column("clause_id", String(64)),
    Column("page", Integer, default=1),
    Column("kind", String(16), default="paragraph"),
    Column("lang", String(8), default="en"),
    Column("confidence", Float, default=1.0),
    Column("table_id", String(64)),
    Column("text_hash", String(64), nullable=False),
)

embeddings = Table(
    "embeddings",
    md,
    Column("model", String(128), primary_key=True),
    Column("text_hash", String(64), primary_key=True),
    Column("dim", Integer, nullable=False),
    Column("vector", LargeBinary, nullable=False),
)

relations = Table(
    "relations",
    md,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(64), nullable=False, index=True),
    Column("src_doc", String(128), nullable=False),
    Column("rel_type", String(32), nullable=False),  # supersedes | modifies | refers_to
    Column("dst_doc", String(128)),
    Column("dst_ref", Text),
    Column("clause_id", String(64)),
    Column("effective_from", String(32)),
    Column("evidence", Text),
    Column("status", String(16), default="auto"),  # auto | approved | rejected
)

tables_ = Table(
    "doc_tables",
    md,
    Column("tenant", String(64), primary_key=True),
    Column("table_id", String(64), primary_key=True),
    Column("doc_id", String(128), nullable=False),
    Column("version", Integer, nullable=False),
    Column("name", Text),
    Column("columns", Text, nullable=False),
    Column("rows", Text, nullable=False),
)

audit = Table(
    "audit",
    md,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(64), nullable=False, index=True),
    Column("ts", Float, nullable=False),
    Column("actor", String(128), nullable=False),
    Column("action", String(64), nullable=False),
    Column("payload", Text, nullable=False),
    Column("prev_hash", String(64), nullable=False),
    Column("hash", String(64), nullable=False),
)

alerts = Table(
    "alerts",
    md,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(64), nullable=False, index=True),
    Column("source", String(128)),
    Column("kind", String(32)),  # new | changed | removed | impact | repair
    Column("title", Text),
    Column("body", Text),
    Column("doc_ids", Text, default="[]"),
    Column("roles", Text, default="[]"),
    Column("impact", Text, default="[]"),
    Column("created_at", Float, nullable=False),
)

source_state = Table(
    "source_state",
    md,
    Column("tenant", String(64), primary_key=True),
    Column("source", String(128), primary_key=True),
    Column("etag", Text),
    Column("last_modified", Text),
    Column("listing_hash", String(64)),
    Column("snapshot", Text, default="{}"),
    Column("last_run", Float),
    Column("last_success", Float),
    Column("last_error", Text),
    Column("runs", Integer, default=0),
    Column("failures", Integer, default=0),
    Column("consecutive_failures", Integer, default=0),
    Column("adapter_version", Integer),
)

jobs = Table(
    "jobs",
    md,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(64), nullable=False),
    Column("kind", String(64), nullable=False),
    Column("payload", Text, nullable=False),
    Column("status", String(16), nullable=False, default="queued"),  # queued | running | done | dead
    Column("attempts", Integer, default=0),
    Column("last_error", Text),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)

memories = Table(
    "memories",
    md,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(64), nullable=False, index=True),
    Column("tier", String(16), nullable=False),  # user | team
    Column("owner", String(128), nullable=False),
    Column("text", Text, nullable=False),
    Column("provenance", Text, default="[]"),
    Column("access", Text, nullable=False),
    Column("status", String(16), nullable=False),  # proposed | approved | rejected
    Column("needs_revalidation", Boolean, default=False),
    Column("doc_id", String(128)),
    Column("created_at", Float, nullable=False),
)

feedback = Table(
    "feedback",
    md,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(64), nullable=False),
    Column("user_id", String(128), nullable=False),
    Column("trace_id", String(64)),
    Column("rating", Integer),
    Column("chunk_id", String(32)),
    Column("comment", Text),
    Column("created_at", Float, nullable=False),
)

traces = Table(
    "traces",
    md,
    Column("trace_id", String(64), primary_key=True),
    Column("tenant", String(64), nullable=False, index=True),
    Column("user_id", String(128), nullable=False),
    Column("ts", Float, nullable=False),
    Column("query", Text),
    Column("data", Text, nullable=False),
)

drafts = Table(
    "drafts",
    md,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(64), nullable=False),
    Column("skill", String(128), nullable=False),
    Column("owner", String(128), nullable=False),
    Column("status", String(16), nullable=False),  # draft | submitted | approved | returned
    Column("content", Text, nullable=False),
    Column("original", Text, nullable=False),
    Column("findings", Text, default="[]"),
    Column("approver", String(128)),
    Column("updated_at", Float, nullable=False),
)


def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, url: str):
        kw: dict[str, Any] = {"future": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
            Path(url.split("///", 1)[-1]).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url, **kw)
        md.create_all(self.engine)

    # ---------- documents and versions

    def get_document(self, tenant: str, doc_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            r = c.execute(select(documents).where(documents.c.tenant == tenant, documents.c.doc_id == doc_id)).first()
        return self._doc(r) if r else None

    def find_by_ref(self, tenant: str, ref: str) -> dict[str, Any] | None:
        """Match a reference number or a declared alias ("GCC" for the current GCC
        edition). A current document wins over a superseded one."""
        norm = normalise_ref(ref)
        if not norm:
            return None
        with self.engine.connect() as c:
            rows = c.execute(select(documents).where(documents.c.tenant == tenant)).all()
        hits = []
        for r in rows:
            d = self._doc(r)
            names = [d.get("ref_no") or "", *d["meta"].get("aliases", [])]
            if any(normalise_ref(n) == norm for n in names if n):
                hits.append(d)
        hits.sort(
            key=lambda d: (bool(d["meta"].get("ref_declared")), d["status"] == "current", d.get("doc_date") or ""),
            reverse=True,
        )
        return hits[0] if hits else None

    def list_documents(self, tenant: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(
                select(documents).where(documents.c.tenant == tenant).order_by(documents.c.updated_at.desc())
            ).all()
        return [self._doc(r) for r in rows]

    def documents_by_ids(self, tenant: str, ids: list[str]) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        with self.engine.connect() as c:
            rows = c.execute(
                select(documents).where(documents.c.tenant == tenant, documents.c.doc_id.in_(set(ids)))
            ).all()
        return {r.doc_id: self._doc(r) for r in rows}

    def upsert_document(self, tenant: str, doc: dict[str, Any]) -> None:
        now = time.time()
        row = {
            "tenant": tenant,
            "doc_id": doc["doc_id"],
            "title": doc["title"],
            "doc_type": doc.get("doc_type", "document"),
            "ref_no": doc.get("ref_no"),
            "doc_date": doc.get("doc_date"),
            "source": doc.get("source"),
            "source_url": doc.get("source_url"),
            "access": _j(doc["access"]),
            "status": doc.get("status", "current"),
            "current_version": doc.get("current_version", 1),
            "meta": _j(doc.get("meta", {})),
            "updated_at": now,
        }
        with self.engine.begin() as c:
            exists = c.execute(
                select(documents.c.doc_id).where(documents.c.tenant == tenant, documents.c.doc_id == doc["doc_id"])
            ).first()
            if exists:
                c.execute(
                    update(documents)
                    .where(documents.c.tenant == tenant, documents.c.doc_id == doc["doc_id"])
                    .values(**row)
                )
            else:
                c.execute(insert(documents).values(**row, created_at=now))

    def set_doc_status(self, tenant: str, doc_id: str, status: str) -> None:
        with self.engine.begin() as c:
            c.execute(
                update(documents)
                .where(documents.c.tenant == tenant, documents.c.doc_id == doc_id)
                .values(status=status, updated_at=time.time())
            )

    def add_version(self, tenant: str, v: dict[str, Any]) -> None:
        with self.engine.begin() as c:
            c.execute(insert(versions).values(tenant=tenant, ingested_at=time.time(), **v))

    def get_versions(self, tenant: str, doc_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(
                select(versions)
                .where(versions.c.tenant == tenant, versions.c.doc_id == doc_id)
                .order_by(versions.c.version)
            ).all()
        return [dict(r._mapping) | {"warnings": json.loads(r.warnings or "[]")} for r in rows]

    def version_by_sha(self, tenant: str, sha: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            r = c.execute(select(versions).where(versions.c.tenant == tenant, versions.c.sha256 == sha)).first()
        return dict(r._mapping) if r else None

    # ---------- chunks

    def current_chunk_ids(self, tenant: str, doc_id: str) -> set[str]:
        with self.engine.connect() as c:
            rows = c.execute(
                select(chunks.c.chunk_id).where(
                    chunks.c.tenant == tenant, chunks.c.doc_id == doc_id, chunks.c.last_version.is_(None)
                )
            ).all()
        return {r.chunk_id for r in rows}

    def insert_chunks(self, tenant: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self.engine.begin() as c:
            for r in rows:
                exists = c.execute(
                    select(chunks.c.chunk_id).where(chunks.c.tenant == tenant, chunks.c.chunk_id == r["chunk_id"])
                ).first()
                if exists:  # a chunk that came back in a later version is current again
                    c.execute(
                        update(chunks)
                        .where(chunks.c.tenant == tenant, chunks.c.chunk_id == r["chunk_id"])
                        .values(last_version=None)
                    )
                else:
                    c.execute(insert(chunks).values(tenant=tenant, **r))

    def close_chunks(self, tenant: str, chunk_ids: set[str], last_version: int) -> None:
        if not chunk_ids:
            return
        with self.engine.begin() as c:
            c.execute(
                update(chunks)
                .where(chunks.c.tenant == tenant, chunks.c.chunk_id.in_(chunk_ids))
                .values(last_version=last_version)
            )

    def get_chunks(self, tenant: str, ids: list[str]) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        with self.engine.connect() as c:
            rows = c.execute(select(chunks).where(chunks.c.tenant == tenant, chunks.c.chunk_id.in_(set(ids)))).all()
        return {r.chunk_id: self._chunk(r) for r in rows}

    def doc_chunks(self, tenant: str, doc_id: str, version: int | None = None) -> list[dict[str, Any]]:
        q = select(chunks).where(chunks.c.tenant == tenant, chunks.c.doc_id == doc_id)
        with self.engine.connect() as c:
            rows = [self._chunk(r) for r in c.execute(q).all()]
        if version is not None:
            rows = [
                r
                for r in rows
                if r["first_version"] <= version and (r["last_version"] is None or r["last_version"] >= version)
            ]
        else:
            rows = [r for r in rows if r["last_version"] is None]
        return rows

    def all_chunks(self, tenant: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            return [self._chunk(r) for r in c.execute(select(chunks).where(chunks.c.tenant == tenant)).all()]

    def clause_chunks(self, tenant: str, doc_id: str, clause_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(
                select(chunks).where(
                    chunks.c.tenant == tenant,
                    chunks.c.doc_id == doc_id,
                    chunks.c.clause_id == clause_id,
                    chunks.c.last_version.is_(None),
                )
            ).all()
        return [self._chunk(r) for r in rows]

    # ---------- embedding cache (keyed by text hash: never pay twice)

    def get_embeddings(self, model: str, hashes: list[str]) -> dict[str, bytes]:
        if not hashes:
            return {}
        out: dict[str, bytes] = {}
        with self.engine.connect() as c:
            for i in range(0, len(hashes), 500):
                part = hashes[i : i + 500]
                for r in c.execute(
                    select(embeddings.c.text_hash, embeddings.c.vector).where(
                        embeddings.c.model == model, embeddings.c.text_hash.in_(part)
                    )
                ).all():
                    out[r.text_hash] = r.vector
        return out

    def put_embeddings(self, model: str, items: dict[str, bytes], dim: int) -> None:
        if not items:
            return
        have = set(self.get_embeddings(model, list(items)))
        rows = [{"model": model, "text_hash": h, "dim": dim, "vector": v} for h, v in items.items() if h not in have]
        if rows:
            with self.engine.begin() as c:
                c.execute(insert(embeddings), rows)

    # ---------- relations (supersession graph)

    def add_relation(self, tenant: str, rel: dict[str, Any]) -> None:
        with self.engine.begin() as c:
            dup = c.execute(
                select(relations.c.id).where(
                    relations.c.tenant == tenant,
                    relations.c.src_doc == rel["src_doc"],
                    relations.c.rel_type == rel["rel_type"],
                    relations.c.dst_ref == rel.get("dst_ref"),
                    relations.c.clause_id == rel.get("clause_id"),
                )
            ).first()
            if not dup:
                c.execute(insert(relations).values(tenant=tenant, **rel))

    def relations_for(self, tenant: str, doc_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            rows = c.execute(
                select(relations).where(
                    relations.c.tenant == tenant, (relations.c.src_doc == doc_id) | (relations.c.dst_doc == doc_id)
                )
            ).all()
        return [dict(r._mapping) for r in rows]

    def all_relations(self, tenant: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(select(relations).where(relations.c.tenant == tenant)).all()]

    def resolve_relations(self, tenant: str) -> list[dict[str, Any]]:
        """Link relations whose target arrived after the source document."""
        resolved = []
        with self.engine.connect() as c:
            rows = c.execute(select(relations).where(relations.c.tenant == tenant, relations.c.dst_doc.is_(None))).all()
        for r in rows:
            d = self.find_by_ref(tenant, r.dst_ref or "")
            if d and d["doc_id"] != r.src_doc:
                self.update_row(relations, {"id": r.id}, dst_doc=d["doc_id"])
                resolved.append(dict(r._mapping) | {"dst_doc": d["doc_id"]})
        return resolved

    # ---------- tables

    def put_table(self, tenant: str, t: dict[str, Any]) -> None:
        with self.engine.begin() as c:
            c.execute(delete(tables_).where(tables_.c.tenant == tenant, tables_.c.table_id == t["table_id"]))
            c.execute(
                insert(tables_).values(tenant=tenant, **{**t, "columns": _j(t["columns"]), "rows": _j(t["rows"])})
            )

    def get_table(self, tenant: str, table_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            r = c.execute(select(tables_).where(tables_.c.tenant == tenant, tables_.c.table_id == table_id)).first()
        if not r:
            return None
        return dict(r._mapping) | {"columns": json.loads(r.columns), "rows": json.loads(r.rows)}

    # ---------- generic small tables

    def insert(self, table: Table, **values: Any) -> int:
        with self.engine.begin() as c:
            res = c.execute(insert(table).values(**values))
            pk = res.inserted_primary_key
            return int(pk[0]) if pk and isinstance(pk[0], int) else 0

    def update_row(self, table: Table, where: dict[str, Any], **values: Any) -> None:
        with self.engine.begin() as c:
            c.execute(update(table).where(and_(*[table.c[k] == v for k, v in where.items()])).values(**values))

    def rows(
        self, table: Table, order_by: str | None = None, desc: bool = True, limit: int | None = None, **where: Any
    ) -> list[dict[str, Any]]:
        q = select(table).where(and_(*[table.c[k] == v for k, v in where.items()])) if where else select(table)
        if order_by:
            col = table.c[order_by]
            q = q.order_by(col.desc() if desc else col)
        if limit:
            q = q.limit(limit)
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(q).all()]

    def count(self, table: Table, **where: Any) -> int:
        q = select(func.count()).select_from(table).where(and_(*[table.c[k] == v for k, v in where.items()]))
        with self.engine.connect() as c:
            return int(c.execute(q).scalar() or 0)

    # ---------- row mappers

    @staticmethod
    def _doc(r: Any) -> dict[str, Any]:
        d = dict(r._mapping)
        d["access"] = json.loads(d["access"])
        d["meta"] = json.loads(d["meta"] or "{}")
        return d

    @staticmethod
    def _chunk(r: Any) -> dict[str, Any]:
        d = dict(r._mapping)
        d["section_path"] = json.loads(d["section_path"] or "[]")
        return d


def normalise_ref(ref: str) -> str:
    return "".join(ch for ch in ref.upper() if ch.isalnum())


# ---------------------------------------------------------------- blobs


class BlobStore(Protocol):
    def put(self, data: bytes, suffix: str = "") -> str: ...
    def get(self, key: str) -> bytes: ...


class LocalBlobStore:
    """Content-addressed, write-once files. Keys are sha256 paths."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes, suffix: str = "") -> str:
        h = hashlib.sha256(data).hexdigest()
        key = f"{h[:2]}/{h}{suffix}"
        p = self.root / key
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
        return key

    def get(self, key: str) -> bytes:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("blob key escapes store root")
        return p.read_bytes()


class S3BlobStore:
    """S3-compatible object store (SeaweedFS, Garage, Ceph). Needs `smriti[s3]`."""

    def __init__(self, url: str):
        import boto3  # type: ignore[import-not-found]

        bucket_prefix = url.removeprefix("s3://")
        self.bucket, _, self.prefix = bucket_prefix.partition("/")
        self.client = boto3.client("s3")

    def put(self, data: bytes, suffix: str = "") -> str:
        h = hashlib.sha256(data).hexdigest()
        key = f"{self.prefix}/{h[:2]}/{h}{suffix}".lstrip("/")
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return key

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()


def make_blob_store(url: str | None, data_dir: Path) -> BlobStore:
    if url and url.startswith("s3://"):
        return S3BlobStore(url)
    return LocalBlobStore(Path(url) if url else data_dir / "blobs")
