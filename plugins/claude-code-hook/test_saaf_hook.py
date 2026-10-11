from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parents[1] / "packages" / "saaf-core" / "src"


def run(kind: str, event: dict, mode: str = "block") -> subprocess.CompletedProcess[str]:
    env = {"PYTHONPATH": str(CORE), "SAAF_HOOK_MODE": mode, "PYTHONIOENCODING": "utf-8", "SYSTEMROOT": "C:\\Windows"}
    return subprocess.run(
        [sys.executable, str(HERE / "saaf_hook.py"), kind],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_blocks_prompt_with_pan() -> None:
    r = run("prompt", {"prompt": "my PAN is ABCPE1234F"})
    assert r.returncode == 2
    assert "1 x PAN" in r.stderr and "ABCPE1234F" not in r.stderr


def test_allows_clean_prompt() -> None:
    assert run("prompt", {"prompt": "refactor this function"}).returncode == 0


def test_warn_mode() -> None:
    assert run("prompt", {"prompt": "PAN ABCPE1234F"}, mode="warn").returncode == 0


def test_tool_input() -> None:
    r = run("tool", {"tool_name": "Write", "tool_input": {"file_path": "x", "content": "aadhaar 2345 6789 0124"}})
    assert r.returncode == 2 and "AADHAAR" in r.stderr
