"""Benchmark harness: detection quality, hard-negative false positives,
restore round-trip under mangling, latency.

Metrics (see docs/benchmark.md):

* per-entity precision / recall / F1, strict (exact span) and relaxed (overlap)
* false positives per 1,000 whitespace tokens on hard-negative documents
* restore round-trip accuracy when tokens come back mangled
* p50 / p99 latency per document
"""

from __future__ import annotations

import json
import random
import re
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from indicpii_bench.adapters import Adapter, Span


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def prf(self) -> tuple[float, float, float]:
        p = self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0
        r = self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        return p, r, f


@dataclass
class Report:
    system: str
    docs: int
    strict: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    relaxed: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    hn_fp: int = 0
    hn_tokens: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    restore_ok: int | None = None
    restore_total: int | None = None

    @staticmethod
    def _micro(table: dict[str, Counts]) -> Counts:
        c = Counts()
        for v in table.values():
            c.tp, c.fp, c.fn = c.tp + v.tp, c.fp + v.fp, c.fn + v.fn
        return c

    def summary(self) -> dict[str, Any]:
        def table(t: dict[str, Counts]) -> dict[str, Any]:
            rows = {
                e: dict(zip(("precision", "recall", "f1"), (round(x, 4) for x in c.prf()), strict=True))
                | {"support": c.tp + c.fn}
                for e, c in sorted(t.items())
            }
            rows["MICRO"] = dict(
                zip(("precision", "recall", "f1"), (round(x, 4) for x in self._micro(t).prf()), strict=True)
            )
            return rows

        lat = sorted(self.latencies_ms)
        return {
            "system": self.system,
            "docs": self.docs,
            "strict": table(self.strict),
            "relaxed": table(self.relaxed),
            "hard_negative_fp_per_1k_tokens": round(1000 * self.hn_fp / max(1, self.hn_tokens), 3),
            "latency_ms": {
                "p50": round(statistics.median(lat), 3) if lat else None,
                "p99": round(lat[min(len(lat) - 1, int(0.99 * len(lat)))], 3) if lat else None,
            },
            "restore_roundtrip": (round(self.restore_ok / self.restore_total, 4) if self.restore_total else None),
        }


def _overlap(a: Span, b: Span) -> bool:
    return a[2] == b[2] and a[0] < b[1] and b[0] < a[1]


def evaluate(
    system: str, adapter: Adapter, docs: list[dict[str, Any]], *, restore: bool = False, seed: int = 0
) -> Report:
    rep = Report(system=system, docs=len(docs))
    for doc in docs:
        text = doc["text"]
        gold: list[Span] = [(s["start"], s["end"], s["entity"]) for s in doc["spans"]]
        t0 = time.perf_counter()
        pred = adapter(text)
        rep.latencies_ms.append((time.perf_counter() - t0) * 1000)

        gold_set, pred_set = set(gold), set(pred)
        for e in {g[2] for g in gold} | {p[2] for p in pred}:
            g_e = {g for g in gold_set if g[2] == e}
            p_e = {p for p in pred_set if p[2] == e}
            rep.strict[e].tp += len(g_e & p_e)
            rep.strict[e].fp += len(p_e - g_e)
            rep.strict[e].fn += len(g_e - p_e)
            matched_g = {g for g in g_e if any(_overlap(g, p) for p in p_e)}
            matched_p = {p for p in p_e if any(_overlap(g, p) for g in g_e)}
            rep.relaxed[e].tp += len(matched_g)
            rep.relaxed[e].fn += len(g_e - matched_g)
            rep.relaxed[e].fp += len(p_e - matched_p)
        if doc.get("hard_negative"):
            rep.hn_tokens += len(text.split())
            rep.hn_fp += len(pred)

    if restore:
        rep.restore_ok, rep.restore_total = restore_roundtrip(docs, seed=seed)
    return rep


_MANGLERS = [
    lambda t: t.lower(),
    lambda t: t.strip("[]"),
    lambda t: t + "'s",
    lambda t: "**" + t.replace("[", "\\[").replace("]", "\\]") + "**",
    lambda t: t.replace("_", " "),
    lambda t: json.dumps({"value": t})[1:-1],
]


def restore_roundtrip(docs: list[dict[str, Any]], seed: int = 0) -> tuple[int, int]:
    """Mask each doc, mangle every token the way models do (case, brackets,
    possessives, markdown escaping, JSON quoting), restore, and count a doc as
    correct when every masked value is back and no token is left over."""
    from saaf import Saaf

    rng = random.Random(seed)
    ok = total = 0
    for doc in docs:
        v = Saaf()
        masked = v.mask(doc["text"])
        if not masked.tokens:
            continue
        total += 1
        mangled = masked.text
        for tok in set(masked.tokens):
            mangled = mangled.replace(tok, rng.choice(_MANGLERS)(tok))
        restored = v.restore(mangled).text
        values_back = all(a.finding.text in restored for a in masked.applied)
        low = restored.lower()
        leftover = any(
            re.search(re.escape(t[1:-1].lower()).replace("_", "[_ ]") + r"(?![0-9])", low) for t in masked.tokens
        )
        if values_back and not leftover:
            ok += 1
    return ok, total


def load(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def markdown(reports: list[dict[str, Any]]) -> str:
    lines = [
        "| System | Strict micro F1 | Relaxed micro F1 | Hard-neg FP / 1k tokens | Restore round-trip | p50 ms | p99 ms |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        rr = r["restore_roundtrip"]
        lines.append(
            f"| {r['system']} | {r['strict']['MICRO']['f1']:.3f} | {r['relaxed']['MICRO']['f1']:.3f} | "
            f"{r['hard_negative_fp_per_1k_tokens']:.2f} | {'-' if rr is None else f'{rr:.3f}'} | "
            f"{r['latency_ms']['p50']} | {r['latency_ms']['p99']} |"
        )
    lines += ["", "Per-entity (strict) for each system:", ""]
    for r in reports:
        lines += [f"**{r['system']}**", "", "| Entity | P | R | F1 | Support |", "|---|---|---|---|---|"]
        for e, row in r["strict"].items():
            if e != "MICRO":
                lines.append(
                    f"| {e} | {row['precision']:.3f} | {row['recall']:.3f} | {row['f1']:.3f} | {row['support']} |"
                )
        lines.append("")
    return "\n".join(lines)
