"""Ask: the query-time pipeline.

understand -> guard input -> resolve access -> hybrid search (filtered) ->
authorise again -> version rules -> rerank -> assemble (with amendments) ->
generate -> verify every citation -> abstain or answer -> trace and audit.

Routing by question type: clause lookups get exact clause-id boosts, "as of"
questions pin the version in force on that date, "what changed" questions pull
both versions, and totals over tables are computed in code from the source
rows rather than written by the model.
"""

from __future__ import annotations

import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import asdict
from datetime import date
from typing import Any

from .engine import Tenant
from .index import tokenize
from .llm import ExtractiveWriter, LLMUnavailable, build_messages
from .metadata import to_iso
from .models import Passage, Principal, class_rank
from .privacy import ConversationMasker
from .store import normalise_ref, traces

ROUTES = [
    ("table", re.compile(r"\b(total|sum|how many|count of|aggregate|add up)\b|कुल|योग", re.I)),
    (
        "compare",
        re.compile(
            r"\b(what changed|changes? (in|to|since)|differen(ce|t)|compare|amend(ed|ment)s?|revised|before and after)\b",
            re.I,
        ),
    ),
    (
        "multihop",
        re.compile(r"\b(which|what) (circulars?|slips?|letters?|documents?) .*\b(modify|amend|supersede|affect)", re.I),
    ),
    ("lookup", re.compile(r"\bclause\s+\d|\b\d{1,3}\.\d{1,3}\b", re.I)),
]
# identifiers that pin a question to one thing: tender/letter numbers and project codes (P-17)
REF_IN_Q = re.compile(r"\b[A-Z]{2,}[A-Z0-9]*(?:[-/][A-Z0-9]+){2,}\b|\b[A-Z]{1,4}-\d{1,4}\b")
AS_OF = re.compile(r"\b(?:as\s+(?:of|on)|on\s+the\s+date|at\s+the\s+time\s+of)\s+(.{6,24})", re.I)

_writer = ExtractiveWriter()


class AnswerCache:
    """Answer cache keyed by the asker's access hash, so one person's answer
    is never served to someone with different rights."""

    def __init__(self, size: int = 512, ttl: float = 900):
        self.size, self.ttl = size, ttl
        self._d: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

    def get(self, key: str) -> dict[str, Any] | None:
        v = self._d.get(key)
        if not v or time.time() - v[0] > self.ttl:
            return None
        self._d.move_to_end(key)
        return v[1]

    def put(self, key: str, val: dict[str, Any]) -> None:
        self._d[key] = (time.time(), val)
        self._d.move_to_end(key)
        while len(self._d) > self.size:
            self._d.popitem(last=False)


_cache = AnswerCache()


def classify_route(q: str) -> str:
    for name, pat in ROUTES:
        if pat.search(q):
            return name
    return "search"


def ask(
    t: Tenant,
    p: Principal,
    question: str,
    *,
    as_of: str | None = None,
    history: list[dict[str, str]] | None = None,
    use_cache: bool = True,
    skill_instructions: str | None = None,
) -> dict[str, Any]:
    events = list(_prepare(t, p, question, as_of, history, skill_instructions, use_cache))
    return events[-1]["data"]


def ask_stream(t: Tenant, p: Principal, question: str, **kw: Any) -> Iterator[dict[str, Any]]:
    """Yields {'event': 'meta'|'token'|'final', 'data': ...} for SSE."""
    yield from _prepare(
        t,
        p,
        question,
        kw.get("as_of"),
        kw.get("history"),
        kw.get("skill_instructions"),
        kw.get("use_cache", True),
        stream=True,
    )


def _prepare(
    t: Tenant,
    p: Principal,
    question: str,
    as_of: str | None,
    history: list[dict[str, str]] | None,
    skill: str | None,
    use_cache: bool,
    stream: bool = False,
) -> Iterator[dict[str, Any]]:
    t0 = time.perf_counter()
    trace_id = uuid.uuid4().hex[:16]
    question = question.strip()
    if not as_of:
        m = AS_OF.search(question)
        if m:
            as_of = to_iso(m.group(1))
    route = classify_route(question)

    # ---- input guardrails
    verdict = t.guard.check_input(question)
    masker = ConversationMasker()
    masked_q, pii_types = masker.mask(question)
    events: list[dict[str, Any]] = list(verdict.events)
    if pii_types:
        events.append({"layer": "input", "check": "pii", "result": f"masked before the model: {', '.join(pii_types)}"})
    if not verdict.allowed:
        res = _result(
            trace_id,
            question,
            verdict.message or "Blocked.",
            [],
            [],
            route,
            as_of,
            events,
            blocked=verdict.category,
            abstained=True,
        )
        t.audit.record(
            p.user_id, "ask_blocked", trace_id=trace_id, query=masked_q, category=verdict.category, score=verdict.score
        )
        _trace(t, p, trace_id, masked_q, res, {})
        yield {"event": "final", "data": res}
        return

    key = f"{p.access_key}|{t.generation}|{as_of}|{skill or ''}|{question.lower()}"
    if use_cache and not history and (hit := _cache.get(key)):
        res = dict(hit, trace_id=trace_id, cached=True)
        t.audit.record(
            p.user_id,
            "ask",
            trace_id=trace_id,
            query=masked_q,
            cached=True,
            cited=[c["doc_id"] for c in res["citations"]],
        )
        yield {"event": "final", "data": res}
        return

    include_sup = route == "compare"
    passages, rtrace = t.retrieve(p, question, as_of=as_of, include_superseded=include_sup)
    for ps in passages:
        if ps.injection_flag:
            events.append(
                {
                    "layer": "retrieval",
                    "check": "injection_scan",
                    "result": f"passage [{ps.n}] contains instruction-like text; wrapped as data",
                    "doc_id": ps.doc_id,
                }
            )
    qtokens = rtrace.pop("qtokens")
    yield {
        "event": "meta",
        "data": {"trace_id": trace_id, "route": route, "as_of": as_of, "passages": [_pdict(x) for x in passages]},
    }

    rc = t.pack.config.retrieval
    top_support = max(rtrace["top_scores"] or [0.0])
    model_name = _writer.name
    answer = ""
    computed: dict[str, Any] | None = None

    if route == "table":
        computed = _table_answer(t, p, question, passages, qtokens)
        if computed:
            answer = computed["answer"]
            model_name = "computed-from-source-rows"

    if not answer and passages and top_support >= rc.min_support:
        if t.gw.available("chat"):
            role_prompt = " ".join(t.pack.roles.roles[r].prompt for r in p.roles if t.pack.roles.roles[r].prompt)
            msgs = build_messages(masked_q, passages, t.pack.config.policy, role_prompt, skill, as_of, history)
            model_name = t.gw.route("chat").model or "chat"  # type: ignore[union-attr]
            try:
                if stream:
                    parts = []
                    for tok in t.gw.stream("chat", msgs):
                        parts.append(tok)
                        yield {"event": "token", "data": tok}  # the final event carries the restored, verified text
                    answer = "".join(parts)
                else:
                    answer = t.gw.complete("chat", msgs)
                answer = masker.restore(answer)
            except LLMUnavailable as e:
                events.append(
                    {
                        "layer": "execution",
                        "check": "model",
                        "result": f"model unavailable, fell back to extractive: {e}",
                    }
                )
                answer = ""
        if not answer:
            answer = _writer.write(question, passages, qtokens, skip=_boilerplate(t))
            model_name = _writer.name

    verification = (
        t.guard.verify(answer, passages)
        if answer
        else {"faithfulness": 0.0, "sentences": [], "cited": [], "citation_ok": False, "threshold": 0.6}
    )
    if computed:
        verification["faithfulness"] = 1.0
        verification["computed"] = computed["method"]
    elif answer and model_name != _writer.name and verification["faithfulness"] < verification["threshold"]:
        # self-correction: a model answer that fails verification is replaced by the verified extractive answer
        events.append(
            {
                "layer": "output",
                "check": "faithfulness",
                "result": f"model answer scored {verification['faithfulness']}; replaced with extractive answer",
            }
        )
        answer = _writer.write(question, passages, qtokens, skip=_boilerplate(t))
        model_name = _writer.name
        verification = t.guard.verify(answer, passages)

    abstained = (not answer) or (
        not computed and (not verification["citation_ok"] or verification["faithfulness"] < verification["threshold"])
    )
    # reference guard: a question about tender X is never answered from tender Y
    missing_ref = None
    if not abstained and not computed:
        refs = REF_IN_Q.findall(question)
        if refs:
            cited_text = " ".join(
                f"{x.text} {x.title} {x.ref_no or ''}" for x in passages if x.n in set(verification.get("cited", []))
            )
            norm = normalise_ref(cited_text)
            if not any(normalise_ref(r) in norm for r in refs):
                abstained, missing_ref = True, refs[0]
                events.append(
                    {"layer": "output", "check": "reference_guard", "result": f"cited sources do not mention {refs[0]}"}
                )
    if abstained:
        answer = _abstain(question, passages, qtokens, as_of, missing_ref)
        events.append({"layer": "output", "check": "abstention", "result": "sources do not support an answer"})
    answer, out_events = t.guard.check_output(answer)
    events += out_events

    cited_ns = set(verification.get("cited", [])) if not abstained else set()
    if computed:
        cited_ns |= set(computed.get("cited", []))
    citations = [_pdict(x) for x in passages if x.n in cited_ns]
    marking = max((c["doc_class"] for c in citations), key=class_rank, default=None)
    if marking and class_rank(marking) >= class_rank("confidential"):
        events.append({"layer": "output", "check": "marking", "result": f"answer cites {marking.upper()} material"})

    res = _result(
        trace_id,
        question,
        answer,
        passages,
        citations,
        route,
        as_of,
        events,
        abstained=abstained,
        verification=verification,
        model=model_name,
        marking=marking,
    )
    res["timings_ms"] = {**rtrace["timings_ms"], "total": round((time.perf_counter() - t0) * 1000, 1)}
    res["retrieval"] = {k: v for k, v in rtrace.items() if k != "timings_ms"}
    if computed:
        res["computed"] = computed
    if use_cache and not history and not abstained:
        _cache.put(key, res)
    t.audit.record(
        p.user_id,
        "ask",
        trace_id=trace_id,
        query=masked_q,
        route=route,
        as_of=as_of,
        retrieved=[x.chunk_id for x in passages],
        cited=[c["doc_id"] for c in citations],
        model=model_name,
        embedder=t.embedder.name,
        reranker=t.reranker.name,
        prompt_version=_prompt_version(t),
        abstained=abstained,
        faithfulness=verification.get("faithfulness"),
        guardrails=[e.get("check") for e in events],
    )
    _trace(t, p, trace_id, masked_q, res, rtrace)
    yield {"event": "final", "data": res}


def _prompt_version(t: Tenant) -> str:
    import hashlib

    from .llm import PLATFORM_RULES

    return hashlib.sha256((PLATFORM_RULES + t.pack.config.policy).encode()).hexdigest()[:10]


def _pdict(x: Passage) -> dict[str, Any]:
    return asdict(x)


def _result(
    trace_id: str,
    question: str,
    answer: str,
    passages: list[Passage],
    citations: list[dict[str, Any]],
    route: str,
    as_of: str | None,
    events: list[dict[str, Any]],
    *,
    abstained: bool = False,
    blocked: str | None = None,
    verification: dict[str, Any] | None = None,
    model: str | None = None,
    marking: str | None = None,
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "question": question,
        "answer": answer,
        "abstained": abstained,
        "blocked": blocked,
        "route": route,
        "as_of": as_of,
        "citations": citations,
        "passages": [_pdict(x) for x in passages],
        "verification": verification or {},
        "guardrails": events,
        "model": model,
        "marking": marking,
        "notice": "AI-assisted answer. Check the cited sources before relying on it in an official document.",
    }


def _abstain(
    question: str, passages: list[Passage], qtokens: list[str], as_of: str | None, missing_ref: str | None = None
) -> str:
    have = set()
    for p in passages:
        have |= set(tokenize(p.text + " " + p.title))
    missing = [t for t in dict.fromkeys(qtokens) if t not in have and not t.isdigit()][:6]
    when = f" as of {as_of}" if as_of else ""
    msg = f"I can't answer this{when} from the documents you have access to."
    if missing_ref:
        msg += f" None of them mentions {missing_ref}."
    elif passages:
        msg += " The closest sources I found don't state it directly."
    if missing:
        msg += f" Not found in those sources: {', '.join(missing)}."
    msg += " If the information exists in a document you can't see, ask your knowledge manager; otherwise it may not be in the memory yet."
    return msg


def _trace(t: Tenant, p: Principal, trace_id: str, masked_q: str, res: dict[str, Any], rtrace: dict[str, Any]) -> None:
    import json

    data = {
        k: res.get(k)
        for k in (
            "route",
            "as_of",
            "abstained",
            "blocked",
            "model",
            "verification",
            "guardrails",
            "timings_ms",
            "retrieval",
        )
    }
    data["passages"] = [
        {k: x[k] for k in ("n", "chunk_id", "doc_id", "score", "status")} for x in res.get("passages", [])
    ]
    t.store.insert(
        traces,
        trace_id=trace_id,
        tenant=t.id,
        user_id=p.user_id,
        ts=time.time(),
        query=masked_q,
        data=json.dumps(data, default=str),
    )


# ---------------------------------------------------------------- tables


NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _table_answer(
    t: Tenant, p: Principal, question: str, passages: list[Passage], qtokens: list[str]
) -> dict[str, Any] | None:
    """Totals come from code over the source rows, never from free text.

    Picks the numeric column whose header best matches the question, filters
    rows by any question terms that appear as cell values (a village, a
    project), sums, and cites the table. With DuckDB installed the same rows
    are also available to the guarded read-only SQL tool.
    """
    seen: set[str] = set()
    best: tuple[float, dict[str, Any], Passage, int, list[list[str]]] | None = None
    q = set(qtokens)
    for ps in passages:
        rows = t.store.get_chunks(t.id, [ps.chunk_id])
        c = rows.get(ps.chunk_id)
        if not c or not c.get("table_id") or c["table_id"] in seen:
            continue
        seen.add(c["table_id"])
        tbl = t.store.get_table(t.id, c["table_id"])
        if not tbl or not tbl["rows"]:
            continue
        # drop summary rows (formulas, "total" labels): totals are recomputed, never trusted
        tbl["rows"] = [
            r
            for r in tbl["rows"]
            if not any(x.startswith("=") or x.strip().lower() in ("total", "grand total") for x in r)
        ]
        for ci, col in enumerate(tbl["columns"]):
            vals = [r[ci] for r in tbl["rows"] if ci < len(r)]
            numeric = [v for v in vals if NUM.fullmatch(v.replace(" ", ""))]
            if len(numeric) < max(1, len(vals) // 2):
                continue
            col_terms = set(tokenize(col))
            score = len(col_terms & q) / (len(col_terms) or 1)
            if score <= 0:
                continue
            filt = [
                r
                for r in tbl["rows"]
                if any(
                    set(tokenize(cell)) & q
                    for j, cell in enumerate(r)
                    if j != ci and not NUM.fullmatch(cell.replace(" ", ""))
                )
            ]
            use = filt if filt and len(filt) < len(tbl["rows"]) else tbl["rows"]
            cand = (score + ps.score * 0.1, tbl, ps, ci, use)
            if best is None or cand[0] > best[0]:
                best = cand
    if not best:
        return None
    _, tbl, ps, ci, use = best
    nums = []
    for r in use:
        if ci < len(r):
            v = r[ci].replace(",", "").replace(" ", "")
            if NUM.fullmatch(v):
                nums.append(float(v))
    if not nums:
        return None
    total = sum(nums)
    total_s = f"{total:,.4f}".rstrip("0").rstrip(".")
    col = tbl["columns"][ci]
    scope = "all rows" if len(use) == len(tbl["rows"]) else f"{len(use)} matching rows"
    return {
        "answer": f"The total of '{col}' is {total_s} across {scope} ({len(nums)} values) in {ps.title}. Computed from the source rows, not generated. [{ps.n}]",
        "method": "sum over source rows",
        "column": col,
        "rows_used": len(nums),
        "total": total,
        "cited": [ps.n],
        "table_id": tbl["table_id"],
    }


def today() -> str:
    return date.today().isoformat()


def _boilerplate(t: Tenant) -> list[re.Pattern[str]]:
    return [re.compile(b, re.I) for b in t.pack.config.retrieval.boilerplate]
