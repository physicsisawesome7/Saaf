#!/usr/bin/env python3
"""Pin every GitHub Action in .github/workflows to a full commit SHA.

    python scripts/pin_actions.py           # rewrite workflows in place
    python scripts/pin_actions.py --check   # exit 1 if any action is unpinned

`uses: owner/repo@v4` becomes `uses: owner/repo@<40-char sha> # v4`, so a
moved or force-pushed tag can't change what runs (the trivy-action tags were
poisoned this way in March 2026). Dependabot keeps pinned SHAs current and
updates the trailing comment.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USES = re.compile(r"(uses:\s*)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)((?:/[A-Za-z0-9_./-]+)?)@([^\s#]+)(\s*#.*)?")
SHA = re.compile(r"^[0-9a-f]{40}$")


def resolve(repo: str, ref: str) -> str:
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/commits/{ref}")
    req.add_header("Accept", "application/vnd.github+json")
    if token := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - fixed https host
        return str(json.load(r)["sha"])


def main() -> int:
    check = "--check" in sys.argv
    cache: dict[tuple[str, str], str] = {}
    unpinned = []
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = wf.read_text(encoding="utf-8")

        def pin(m: re.Match[str], wf: Path = wf) -> str:
            prefix, repo, sub, ref, _comment = m.groups()
            if SHA.match(ref):
                return m.group(0)
            if check:
                unpinned.append(f"{wf.name}: {repo}{sub}@{ref}")
                return m.group(0)
            key = (repo, ref)
            if key not in cache:
                cache[key] = resolve(repo, ref)
                print(f"{repo}@{ref} -> {cache[key]}")
            return f"{prefix}{repo}{sub}@{cache[key]} # {ref}"

        new = USES.sub(pin, text)
        if new != text and not check:
            wf.write_text(new, encoding="utf-8", newline="\n")
    if unpinned:
        print("unpinned actions:", *unpinned, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
