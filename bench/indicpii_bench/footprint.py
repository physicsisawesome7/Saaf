"""Installed footprint of each system's Python stack (bytes on disk).

Measured from the running interpreter's installed distributions, following
`Requires-Dist` transitively (extras ignored), plus spaCy models if present.
Run it inside the environment that has the competitor installed.
"""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
_NAME = re.compile(r"^[A-Za-z0-9_.\-]+")


def _dist_size(dist: metadata.Distribution) -> int:
    total = 0
    for f in dist.files or []:
        try:
            p = Path(str(dist.locate_file(f)))
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def _closure(name: str) -> dict[str, int]:
    seen: dict[str, int] = {}
    stack = [name]
    while stack:
        n = stack.pop().lower().replace("_", "-")
        if n in seen:
            continue
        try:
            dist = metadata.distribution(n)
        except metadata.PackageNotFoundError:
            continue
        seen[n] = _dist_size(dist)
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            m = _NAME.match(req.strip())
            if m:
                stack.append(m.group(0))
    return seen


def _mb(n: int) -> float:
    return round(n / 1_048_576, 1)


def report() -> dict[str, Any]:
    out: dict[str, Any] = {}
    core = (
        sum(p.stat().st_size for p in (ROOT / "packages" / "saaf-core" / "src" / "saaf").rglob("*.py"))
        + (ROOT / "packages" / "saaf-core" / "src" / "saaf" / "_data" / "entities.json").stat().st_size
    )
    out["saaf-core (zero dependencies)"] = {"total_mb": _mb(core), "packages": 1}
    pres = _closure("presidio-analyzer")
    if pres:
        models = {k: v for k, v in _closure("en-core-web-lg").items() if k.startswith("en-core")}
        allp = {**pres, **models}
        out["presidio-analyzer + en_core_web_lg"] = {
            "total_mb": _mb(sum(allp.values())),
            "packages": len(allp),
            "largest": {k: _mb(v) for k, v in sorted(allp.items(), key=lambda kv: -kv[1])[:5]},
        }
    return out
