"""Hybrid search: dense + keyword, fused with reciprocal rank fusion, filtered
by access *during* search, then reranked.

Backends behind one interface:

* ``LocalIndex``: numpy dense matrix plus an in-memory BM25 inverted index.
  Right for pilots up to a few hundred thousand chunks on one box.
* ``QdrantIndex``: Qdrant named dense + sparse (IDF) vectors with server-side
  RRF fusion and payload filters. The default for production; Milvus is the
  escalation path past hundreds of millions of vectors.

Embedders and rerankers are pluggable the same way. The built-in hashing
embedder needs no model download, so a fresh install answers questions in
seconds; production points ``models.embed`` at Qwen3-Embedding or BGE-M3
served by vLLM/TEI. The embedding model name is stored with every vector, so
an upgrade is a background re-index with a blue-green cutover.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import threading
import unicodedata
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import numpy as np

from .config import ModelRoute

TOKEN = re.compile(r"\d+(?:\.\d+)+|[\wऀ-ॿ]+", re.UNICODE)
STOP = set(
    "a an the of and or to in on for by with as at is are was were be been this that these those it its from which "
    "what who whom how when where why does do did shall will would should can could may might than then there their "
    "has have had not no any all such per into about under over my me i we our you your he she they them his her "
    "tell please give show say says said is? kya hai ka ki ke ko se mein "
    "के का की को से में है हैं क्या और या पर यह वह एक भी तो ही था थे थी लिए कौन कब कहाँ कैसे किस किसी दौरान".split()
)
DEVANAGARI_CH = re.compile(r"[ऀ-ॿ]")


def coverage(terms: dict[str, float], have: set[str]) -> float:
    """Weighted share of query terms present, judged per script.

    A Hindi question expanded with English synonyms is covered either by a
    Hindi passage (Hindi terms) or an English one (English terms); mixing the
    two into one denominator would penalise both."""
    groups: dict[bool, dict[str, float]] = {True: {}, False: {}}
    for t, w in terms.items():
        groups[bool(DEVANAGARI_CH.search(t))][t] = w
    best = 0.0
    for g in groups.values():
        total = sum(g.values())
        if total:
            best = max(best, sum(w for t, w in g.items() if t in have) / total)
    return best


_SPLIT = re.compile(r"(?:(?<=[.।?!])|(?<=[.।?!][\"”']))\s+(?=[A-Z0-9(\[ऀ-ॿ\"“'])|(?<=:)\s+(?=[\"“])|\n+")
_ABBR = re.compile(r"\b(?:No|Nos|Rs|Sr|Dr|Mr|Mrs|Ms|Smt|Shri|Sri|vs|viz|i\.e|e\.g|Cl|Para|Rly|Govt|Dy|Asst)\.$", re.I)


def split_sentences(text: str) -> list[str]:
    """Sentence split that keeps "Correction Slip No. 7" and "Rs. 5" whole and
    separates a quoted clause from the line that introduces it."""
    out: list[str] = []
    for piece in _SPLIT.split(text):
        piece = piece.strip()
        if not piece:
            continue
        if out and _ABBR.search(out[-1]):
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    return out


def _stem(t: str) -> str:
    """Light English suffix stripping: enough to join submit/submitting/submitted."""
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    for suf in ("ing", "ed"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            t = t[: -len(suf)]
            if len(t) > 3 and t[-1] == t[-2] and t[-1] not in "lsz":
                t = t[:-1]
            return t
    if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    out = []
    for t in TOKEN.findall(text):
        if t in STOP or (len(t) == 1 and not t.isdigit()):
            continue
        if t.isascii() and not t[0].isdigit():
            t = _stem(t)
        out.append(t)
    return out


# ---------------------------------------------------------------- embedders


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray: ...


class HashingEmbedder:
    """Deterministic feature-hashing embedder (words, bigrams, char n-grams).

    Not semantic in the way a trained model is, but script-agnostic (Hindi and
    English), robust to spelling variants through char n-grams, free, and
    instant. It exists so the platform works offline on day one.
    """

    name = "smriti-hash-v1"

    def __init__(self, dim: int = 768):
        self.dim = dim

    def _h(self, feat: str) -> tuple[int, float]:
        d = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
        n = int.from_bytes(d, "little")
        return n % self.dim, (1.0 if (n >> 63) & 1 else -1.0)

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = tokenize(t)
            feats: dict[str, float] = defaultdict(float)
            for tok in toks:
                feats["w:" + tok] += 1.0
                padded = f"#{tok}#"
                grams = [padded[j : j + 4] for j in range(max(1, len(padded) - 3))]
                for g in grams:
                    feats["c:" + g] += 0.35 / max(1, len(grams)) * 3
            for a, b in zip(toks, toks[1:], strict=False):
                feats[f"b:{a}_{b}"] += 0.6
            for f, w in feats.items():
                idx, sign = self._h(f)
                out[i, idx] += sign * (1.0 + math.log(w)) if w >= 1 else sign * w
            n = np.linalg.norm(out[i])
            if n:
                out[i] /= n
        return out


class OpenAICompatEmbedder:
    """Any OpenAI-compatible /v1/embeddings server: vLLM, TEI, Ollama, LiteLLM."""

    def __init__(self, route: ModelRoute, query_instruction: str | None = None):
        assert route.base_url and route.model
        self.route = route
        self.name = route.model
        self.query_instruction = (
            query_instruction or "Instruct: Given a question, retrieve passages that answer it\nQuery: "
        )
        key = os.environ.get(route.api_key_env or "", "") if route.api_key_env else ""
        self.client = httpx.Client(
            base_url=route.base_url.rstrip("/"),
            timeout=route.timeout_s,
            headers={"Authorization": f"Bearer {key}"} if key else {},
        )
        self.dim = len(self._call(["dimension probe"])[0])

    def _call(self, texts: list[str]) -> list[list[float]]:
        r = self.client.post("/embeddings", json={"model": self.route.model, "input": texts})
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        if query:
            texts = [self.query_instruction + t for t in texts]
        vecs: list[list[float]] = []
        for i in range(0, len(texts), 64):
            vecs.extend(self._call(texts[i : i + 64]))
        arr = np.asarray(vecs, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.where(norms == 0, 1, norms)


# ---------------------------------------------------------------- indexes


@dataclass
class Hit:
    chunk_id: str
    score: float
    dense_rank: int | None
    sparse_rank: int | None
    payload: dict[str, Any]


class VectorIndex(Protocol):
    def upsert(self, items: list[tuple[str, np.ndarray, str, dict[str, Any]]]) -> None: ...
    def set_payload(self, chunk_ids: list[str], updates: dict[str, Any]) -> None: ...
    def set_payload_where(self, doc_id: str, updates: dict[str, Any]) -> None: ...
    def delete(self, chunk_ids: list[str]) -> None: ...
    def search(
        self,
        qvec: np.ndarray,
        qtokens: list[str],
        allow: Callable[[dict[str, Any]], bool],
        qfilter: dict[str, Any] | None,
        k: int,
        rrf_k: int,
        current_only: bool,
    ) -> list[Hit]: ...
    def __len__(self) -> int: ...


class LocalIndex:
    def __init__(self, dim: int):
        self.dim = dim
        self._lock = threading.RLock()
        self.ids: list[str] = []
        self.pos: dict[str, int] = {}
        self.payloads: list[dict[str, Any]] = []
        self.alive: list[bool] = []
        self.mat = np.zeros((0, dim), dtype=np.float32)
        self._pending: list[np.ndarray] = []
        self.postings: dict[str, dict[int, int]] = defaultdict(dict)
        self.doclen: list[int] = []

    def __len__(self) -> int:
        return sum(self.alive)

    def _flush(self) -> None:
        if self._pending:
            self.mat = np.vstack([self.mat, *self._pending]) if len(self.mat) else np.vstack(self._pending)
            self._pending = []

    def upsert(self, items: list[tuple[str, np.ndarray, str, dict[str, Any]]]) -> None:
        with self._lock:
            for cid, vec, text, payload in items:
                if cid in self.pos:
                    i = self.pos[cid]
                    self._flush()
                    self.mat[i] = vec
                    self.payloads[i] = payload
                    self.alive[i] = True
                    continue
                i = len(self.ids)
                self.ids.append(cid)
                self.pos[cid] = i
                self.payloads.append(payload)
                self.alive.append(True)
                self._pending.append(vec.reshape(1, -1).astype(np.float32))
                toks = tokenize(text)
                self.doclen.append(len(toks))
                tf: dict[str, int] = defaultdict(int)
                for t in toks:
                    tf[t] += 1
                for t, n in tf.items():
                    self.postings[t][i] = n

    def set_payload(self, chunk_ids: list[str], updates: dict[str, Any]) -> None:
        with self._lock:
            for cid in chunk_ids:
                if cid in self.pos:
                    self.payloads[self.pos[cid]].update(updates)

    def set_payload_where(self, doc_id: str, updates: dict[str, Any]) -> None:
        with self._lock:
            for p in self.payloads:
                if p.get("doc_id") == doc_id:
                    p.update(updates)

    def delete(self, chunk_ids: list[str]) -> None:
        with self._lock:
            for cid in chunk_ids:
                if cid in self.pos:
                    self.alive[self.pos[cid]] = False

    def search(self, qvec, qtokens, allow, qfilter, k, rrf_k, current_only):  # type: ignore[no-untyped-def]
        with self._lock:
            self._flush()
            n = len(self.ids)
            if n == 0:
                return []
            # Filter first: unauthorised or retired chunks never enter ranking.
            ok = np.fromiter(
                (
                    self.alive[i]
                    and (not current_only or self.payloads[i].get("current", True))
                    and allow(self.payloads[i])
                    for i in range(n)
                ),
                dtype=bool,
                count=n,
            )
            if not ok.any():
                return []
            dense = self.mat @ qvec.astype(np.float32)
            dense[~ok] = -np.inf
            d_order = np.argsort(-dense)[:k]
            d_rank = {int(i): r for r, i in enumerate(d_order) if np.isfinite(dense[i])}

            scores: dict[int, float] = defaultdict(float)
            avgdl = (sum(self.doclen) / n) or 1.0
            for t in set(qtokens):
                post = self.postings.get(t)
                if not post:
                    continue
                idf = math.log(1 + (n - len(post) + 0.5) / (len(post) + 0.5))
                for i, tf in post.items():
                    if not ok[i]:
                        continue
                    dl = self.doclen[i]
                    scores[i] += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * dl / avgdl))
            s_order = sorted(scores, key=scores.__getitem__, reverse=True)[:k]
            s_rank = {i: r for r, i in enumerate(s_order)}

            fused: dict[int, float] = defaultdict(float)
            for i, r in d_rank.items():
                fused[i] += 1.0 / (rrf_k + r + 1)
            for i, r in s_rank.items():
                fused[i] += 1.0 / (rrf_k + r + 1)
            top = sorted(fused, key=fused.__getitem__, reverse=True)[:k]
            return [Hit(self.ids[i], fused[i], d_rank.get(i), s_rank.get(i), self.payloads[i]) for i in top]


class QdrantIndex:
    """Qdrant backend (Apache 2.0, Rust). Needs ``smriti[qdrant]``."""

    def __init__(self, url: str, collection: str, dim: int):
        from qdrant_client import QdrantClient, models  # type: ignore[import-not-found]

        self.m = models
        self.client = QdrantClient(url=url)
        self.collection = collection
        self.dim = dim
        if not self.client.collection_exists(collection):
            self.client.create_collection(
                collection,
                vectors_config={"dense": models.VectorParams(size=dim, distance=models.Distance.COSINE, on_disk=True)},
                sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
                quantization_config=models.ScalarQuantization(
                    scalar=models.ScalarQuantizationConfig(type=models.ScalarType.INT8, always_ram=True)
                ),
            )
            for key, schema in [
                ("doc_id", "keyword"),
                ("doc_type", "keyword"),
                ("current", "bool"),
                ("access.doc_class", "keyword"),
                ("access.divisions", "keyword"),
                ("access.projects", "keyword"),
                ("access.groups", "keyword"),
            ]:
                self.client.create_payload_index(collection, key, field_schema=schema)

    @staticmethod
    def _pid(cid: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, cid))

    @staticmethod
    def _sparse(tokens: list[str]) -> tuple[list[int], list[float]]:
        tf: dict[int, float] = defaultdict(float)
        for t in tokens:
            tf[int.from_bytes(hashlib.blake2b(t.encode(), digest_size=4).digest(), "little")] += 1.0
        return list(tf), list(tf.values())

    def __len__(self) -> int:
        return int(self.client.count(self.collection).count)

    def upsert(self, items):  # type: ignore[no-untyped-def]
        pts = []
        for cid, vec, text, payload in items:
            idx, val = self._sparse(tokenize(text))
            pts.append(
                self.m.PointStruct(
                    id=self._pid(cid),
                    vector={"dense": vec.tolist(), "sparse": self.m.SparseVector(indices=idx, values=val)},
                    payload={**payload, "chunk_id": cid},
                )
            )
        for i in range(0, len(pts), 256):
            self.client.upsert(self.collection, points=pts[i : i + 256])

    def set_payload(self, chunk_ids, updates):  # type: ignore[no-untyped-def]
        self.client.set_payload(self.collection, payload=updates, points=[self._pid(c) for c in chunk_ids])

    def set_payload_where(self, doc_id, updates):  # type: ignore[no-untyped-def]
        flt = self.m.Filter(must=[self.m.FieldCondition(key="doc_id", match=self.m.MatchValue(value=doc_id))])
        self.client.set_payload(self.collection, payload=updates, points=flt)

    def delete(self, chunk_ids):  # type: ignore[no-untyped-def]
        self.client.delete(self.collection, points_selector=[self._pid(c) for c in chunk_ids])

    def search(self, qvec, qtokens, allow, qfilter, k, rrf_k, current_only):  # type: ignore[no-untyped-def]
        flt = dict(qfilter or {})
        if current_only:
            flt.setdefault("must", []).append({"key": "current", "match": {"value": True}})
        f = self.m.Filter.model_validate(flt) if flt else None
        idx, val = self._sparse(qtokens)
        res = self.client.query_points(
            self.collection,
            prefetch=[
                self.m.Prefetch(query=qvec.tolist(), using="dense", limit=k, filter=f),
                self.m.Prefetch(query=self.m.SparseVector(indices=idx, values=val), using="sparse", limit=k, filter=f),
            ],
            query=self.m.FusionQuery(fusion=self.m.Fusion.RRF),
            limit=k,
            with_payload=True,
        ).points
        return [Hit(p.payload["chunk_id"], float(p.score), None, None, p.payload) for p in res if allow(p.payload)]


# ---------------------------------------------------------------- rerankers


class Reranker(Protocol):
    name: str

    def score(self, query: str, qtokens: list[str], texts: list[str], prior: list[float]) -> list[float]: ...


class LexicalReranker:
    """Coverage-based reranker used when no cross-encoder is configured.

    Rewards passages that contain more of the distinct query terms (rarer terms
    weigh more), exact clause-number matches and phrase matches. Returns a
    0..1 support score that the abstention gate also reads.
    """

    name = "lexical-coverage-v1"

    def __init__(self, idf: Callable[[str], float] | None = None):
        self.idf = idf or (lambda t: 1.0)

    def score(self, query, qtokens, texts, prior):  # type: ignore[no-untyped-def]
        terms = list(dict.fromkeys(qtokens))
        if not terms:
            return [0.0 for _ in texts]
        weights = {t: self.idf(t) for t in terms}
        clause_ids = set(re.findall(r"\b\d{1,3}(?:\.\d{1,3})+\b", query))
        pmax = max(prior) if prior else 1.0
        out = []
        q_bigrams = {f"{a} {b}" for a, b in zip(terms, terms[1:], strict=False)}
        for text, pr in zip(texts, prior, strict=False):
            toks = tokenize(text)
            have = set(toks)
            cov = coverage(weights, have)
            bigr = {f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False)}
            phrase = len(q_bigrams & bigr) / len(q_bigrams) if q_bigrams else 0.0
            # the passage *is* the clause asked about (its header names it) vs merely mentions it
            header = text.split("\n", 1)[0].lower()
            if clause_ids and any(f"clause {c}" in header for c in clause_ids):
                clause = 0.35
            elif clause_ids and clause_ids & set(re.findall(r"\b\d{1,3}(?:\.\d{1,3})+\b", text)):
                clause = 0.1
            else:
                clause = 0.0
            out.append(round(0.65 * cov + 0.15 * phrase + clause + 0.1 * (pr / pmax if pmax else 0), 4))
        return out


class HttpReranker:
    """Cross-encoder served with a TEI-compatible /rerank endpoint
    (bge-reranker-v2-m3, Qwen3 reranker)."""

    def __init__(self, route: ModelRoute):
        assert route.base_url
        self.route = route
        self.name = route.model or "http-reranker"
        self.client = httpx.Client(base_url=route.base_url.rstrip("/"), timeout=route.timeout_s)

    def score(self, query, qtokens, texts, prior):  # type: ignore[no-untyped-def]
        r = self.client.post("/rerank", json={"query": query, "texts": texts, "raw_scores": False})
        r.raise_for_status()
        scores = [0.0] * len(texts)
        for item in r.json():
            scores[item["index"]] = float(item["score"])
        return scores
