"""``saaf`` command-line interface.

    saaf scan FILE... [--json] [--fail-on-findings]   find PII (CI / pre-commit friendly)
    saaf mask [FILE] [--vault PATH]                   mask text from a file or stdin
    saaf restore [FILE] --vault PATH                  restore tokens using a saved vault
    saaf entities                                      list supported entity types
    saaf validate ENTITY VALUE                         run one validator
    saaf audit verify FILE                             verify a signed audit log
    saaf evidence --audit FILE [--policy FILE]         build an evidence pack

Raw values are never printed unless ``--show-values`` is given. Persistent
vaults are encrypted with the 32-byte hex key in ``SAAF_VAULT_KEY``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from saaf._version import __version__
from saaf.audit import read_jsonl, verify_chain
from saaf.detect import Detector
from saaf.engine import Saaf
from saaf.evidence import build_evidence
from saaf.policy import Policy
from saaf.spec import canonicalize, default_spec
from saaf.vault import InMemoryVault, SQLiteVault, StaticKeyProvider, Vault


def _read(path: str | None) -> str:
    if path in (None, "-"):
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _policy(args: argparse.Namespace) -> Policy:
    return Policy.load(args.policy) if getattr(args, "policy", None) else Policy()


def _vault(path: str | None, allow_plaintext: bool) -> Vault:
    if not path:
        return InMemoryVault()
    key_hex = os.environ.get("SAAF_VAULT_KEY")
    keys = StaticKeyProvider({"default": bytes.fromhex(key_hex)}) if key_hex else None
    return SQLiteVault(path, keys=keys, allow_plaintext=allow_plaintext, ttl=None)


_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
_BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".whl", ".so", ".dll", ".exe", ".db"}


def _expand(paths: Sequence[str]) -> list[str]:
    """Files as given; directories walked recursively (skipping VCS, deps and binaries)."""
    out: list[str] = []
    for p in paths:
        path = Path(p)
        if p != "-" and path.is_dir():
            out += sorted(
                str(f)
                for f in path.rglob("*")
                if f.is_file()
                and f.suffix.lower() not in _BINARY_SUFFIXES
                and not _SKIP_DIRS.intersection(f.relative_to(path).parts)
            )
        else:
            out.append(p)
    return out


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    col = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return line, col


def cmd_scan(args: argparse.Namespace) -> int:
    policy = _policy(args)
    entities = args.entities.split(",") if args.entities else policy.enabled_entities
    detector = Detector(entities=entities)
    saaf = Saaf(policy, detector=detector)
    total = 0
    report = []
    for path in _expand(args.files or ["-"]):
        text = _read(path)
        findings = saaf.scan(text) if args.threshold is None else detector.scan(text, threshold=args.threshold)
        total += len(findings)
        for f in findings:
            line, col = _line_col(text, f.start)
            item = {"file": path, "line": line, "col": col, **f.to_dict(include_text=args.show_values)}
            report.append(item)
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        for r in report:
            value = f"  {r['text']!r}" if args.show_values else ""
            flags = "".join(
                [
                    " validated" if r["validated"] else "",
                    " context" if r["context_hit"] else "",
                    " ocr-repaired" if r.get("ocr_repaired") else "",
                ]
            )
            print(f"{r['file']}:{r['line']}:{r['col']}: {r['entity']} score={r['score']}{flags}{value}")
        print(f"{total} finding(s)", file=sys.stderr)
    return 1 if (args.fail_on_findings and total) else 0


def cmd_mask(args: argparse.Namespace) -> int:
    saaf = Saaf(_policy(args), vault=_vault(args.vault, args.allow_plaintext))
    result = saaf.mask(_read(args.file), destination=args.destination)
    if result.blocked:
        print(f"blocked by policy: {result.summary()['entity_counts']}", file=sys.stderr)
        return 2
    sys.stdout.write(result.text)
    if args.summary:
        print(json.dumps(result.summary()), file=sys.stderr)
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    saaf = Saaf(_policy(args), vault=_vault(args.vault, args.allow_plaintext))
    result = saaf.restore(_read(args.file))
    sys.stdout.write(result.text)
    if result.unknown:
        print(f"warning: {len(result.unknown)} unknown token(s) left in output", file=sys.stderr)
    return 0


def cmd_entities(args: argparse.Namespace) -> int:
    spec = default_spec()
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": e.id,
                        "label": e.label,
                        "phase": e.phase,
                        "severity": e.severity,
                        "validator": e.validator_name,
                    }
                    for e in spec.entities
                ],
                indent=2,
            )
        )
        return 0
    print(f"spec {spec.version}")
    for e in spec.entities:
        print(
            f"  {e.id:<16} {e.phase}  {e.severity:<8} {e.label}"
            + (f"  [{e.validator_name}]" if e.validator_name else "")
        )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    spec = default_spec()
    e = spec.by_id.get(args.entity.upper())
    if e is None:
        print(f"unknown entity {args.entity!r}", file=sys.stderr)
        return 2
    if e.validator is None:
        print(f"{e.id} has no validator (pattern + context only)")
        return 0
    ok = e.validator(canonicalize(e.canonical, args.value))
    print("valid" if ok else "invalid")
    return 0 if ok else 1


def cmd_audit_verify(args: argparse.Namespace) -> int:
    key = os.environ.get("SAAF_AUDIT_KEY")
    if not key:
        print("set SAAF_AUDIT_KEY (hex) to verify signatures", file=sys.stderr)
        return 2
    ok, msg = verify_chain(read_jsonl(args.file), bytes.fromhex(key))
    print(msg)
    return 0 if ok else 1


def cmd_evidence(args: argparse.Namespace) -> int:
    key = os.environ.get("SAAF_AUDIT_KEY")
    md = build_evidence(
        _policy(args),
        read_jsonl(args.audit),
        audit_key=bytes.fromhex(key) if key else None,
        processors=args.processor or [],
    )
    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="saaf", description="India-first PII masking and restore for LLM traffic.")
    p.add_argument("--version", action="version", version=f"saaf {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="detect PII in files or stdin")
    s.add_argument("files", nargs="*")
    s.add_argument("--json", action="store_true")
    s.add_argument("--show-values", action="store_true", help="print matched values (careful: this prints PII)")
    s.add_argument("--entities", help="comma-separated entity ids to enable")
    s.add_argument("--threshold", type=float)
    s.add_argument("--policy")
    s.add_argument("--fail-on-findings", action="store_true", help="exit 1 if anything is found")
    s.set_defaults(func=cmd_scan)

    for name, func in (("mask", cmd_mask), ("restore", cmd_restore)):
        m = sub.add_parser(name, help=f"{name} text from a file or stdin")
        m.add_argument("file", nargs="?")
        m.add_argument("--policy")
        m.add_argument("--vault", help="SQLite vault path (encrypted with SAAF_VAULT_KEY)")
        m.add_argument("--allow-plaintext", action="store_true", help="allow an unencrypted vault (testing only)")
        if name == "mask":
            m.add_argument("--destination")
            m.add_argument("--summary", action="store_true", help="print types/counts summary to stderr")
        m.set_defaults(func=func)

    e = sub.add_parser("entities", help="list supported entity types")
    e.add_argument("--json", action="store_true")
    e.set_defaults(func=cmd_entities)

    v = sub.add_parser("validate", help="run one entity's validator on a value")
    v.add_argument("entity")
    v.add_argument("value")
    v.set_defaults(func=cmd_validate)

    a = sub.add_parser("audit", help="audit log tools")
    asub = a.add_subparsers(dest="audit_command", required=True)
    av = asub.add_parser("verify", help="verify signatures and hash chain")
    av.add_argument("file")
    av.set_defaults(func=cmd_audit_verify)

    ev = sub.add_parser("evidence", help="build a Markdown evidence pack")
    ev.add_argument("--audit", required=True)
    ev.add_argument("--policy")
    ev.add_argument("--processor", action="append", help="declare a downstream processor (repeatable)")
    ev.add_argument("-o", "--output")
    ev.set_defaults(func=cmd_evidence)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
