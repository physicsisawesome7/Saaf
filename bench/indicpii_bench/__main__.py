"""IndicPII-Bench command line.

python -m indicpii_bench generate --n 420 --seed 7 -o corpus/v0/docs.jsonl
python -m indicpii_bench run --corpus corpus/v0/docs.jsonl --systems saaf,regex-baseline
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from indicpii_bench.adapters import ADAPTERS, AdapterUnavailable
from indicpii_bench.generate import generate, write
from indicpii_bench.harness import evaluate, load, markdown


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="indicpii-bench")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--n", type=int, default=420)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("-o", "--output", required=True)
    f = sub.add_parser("fetch", help="download licence-cleared external data and build lexicons")
    f.add_argument("--offline", action="store_true", help="rebuild from files already in data/raw")
    g1 = sub.add_parser("generate-v1", help="synthetic corpus v1 in named slices (needs `fetch` lexicons)")
    g1.add_argument("--per-slice", type=int, default=150)
    g1.add_argument("--seed", type=int, default=23)
    g1.add_argument("-o", "--output", required=True)
    sw = sub.add_parser("sweep", help="pick a score threshold for presidio-tuned on a dev corpus")
    sw.add_argument("--corpus", action="append", required=True)
    sub.add_parser("footprint", help="installed size of each system's Python stack")
    r = sub.add_parser("run")
    r.add_argument("--corpus", action="append", required=True, help="repeatable; corpora are concatenated")
    r.add_argument("--systems", default="saaf,regex-baseline")
    r.add_argument("--out-dir", default="results")
    args = p.parse_args(argv)

    if args.cmd == "fetch":
        from indicpii_bench.fetch import run as fetch_run

        fetch_run(offline=args.offline)
        return 0

    if args.cmd == "generate":
        docs = generate(args.n, args.seed)
        write(args.output, docs)
        print(f"wrote {len(docs)} docs to {args.output}")
        return 0

    if args.cmd == "generate-v1":
        from indicpii_bench.corpus_v1 import generate_v1

        docs = generate_v1(args.per_slice, args.seed)
        write(args.output, docs)
        print(f"wrote {len(docs)} docs to {args.output}")
        return 0

    if args.cmd == "footprint":
        from indicpii_bench.footprint import report as footprint_report

        print(json.dumps(footprint_report(), indent=2))
        return 0

    docs = [d for path in args.corpus for d in load(path)]

    if args.cmd == "sweep":
        from indicpii_bench.adapters import _presidio_engine, _presidio_runner

        engine = _presidio_engine(india=True, saaf=False)
        for th in (0.3, 0.4, 0.5, 0.6, 0.7, 0.85):
            s = evaluate(f"presidio@{th}", _presidio_runner(engine, th), docs).summary()
            print(
                f"threshold {th}: strict micro F1 {s['strict']['MICRO']['f1']:.4f}  "
                f"hard-neg FP/1k {s['hard_negative_fp_per_1k_tokens']}"
            )
        return 0

    reports = []
    for name in args.systems.split(","):
        t0 = time.perf_counter()
        try:
            adapter = ADAPTERS[name]()
        except AdapterUnavailable as exc:
            print(f"skip {name}: {exc}", file=sys.stderr)
            continue
        cold = (time.perf_counter() - t0) * 1000
        reports.append(evaluate(name, adapter, docs, restore=(name == "saaf"), cold_start_ms=cold).summary())
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    md = markdown(reports)
    (out / "results.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
