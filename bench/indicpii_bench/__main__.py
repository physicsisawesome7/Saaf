"""IndicPII-Bench command line.

python -m indicpii_bench generate --n 420 --seed 7 -o corpus/v0/docs.jsonl
python -m indicpii_bench run --corpus corpus/v0/docs.jsonl --systems saaf,regex-baseline
"""

from __future__ import annotations

import argparse
import json
import sys
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
    r = sub.add_parser("run")
    r.add_argument("--corpus", required=True)
    r.add_argument("--systems", default="saaf,regex-baseline")
    r.add_argument("--out-dir", default="results")
    args = p.parse_args(argv)

    if args.cmd == "generate":
        docs = generate(args.n, args.seed)
        write(args.output, docs)
        print(f"wrote {len(docs)} docs to {args.output}")
        return 0

    docs = load(args.corpus)
    reports = []
    for name in args.systems.split(","):
        try:
            adapter = ADAPTERS[name]()
        except AdapterUnavailable as exc:
            print(f"skip {name}: {exc}", file=sys.stderr)
            continue
        reports.append(evaluate(name, adapter, docs, restore=(name == "saaf")).summary())
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    md = markdown(reports)
    (out / "results.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
