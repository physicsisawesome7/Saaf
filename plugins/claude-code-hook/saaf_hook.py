#!/usr/bin/env python3
"""Claude Code hook: stop prompts and file writes that contain Indian PII.

Install (project ``.claude/settings.json`` or user ``~/.claude/settings.json``)::

    {
      "hooks": {
        "UserPromptSubmit": [
          {"hooks": [{"type": "command", "command": "python /path/to/saaf_hook.py prompt"}]}
        ],
        "PreToolUse": [
          {"matcher": "Write|Edit|Bash",
           "hooks": [{"type": "command", "command": "python /path/to/saaf_hook.py tool"}]}
        ]
      }
    }

Behaviour is set with ``SAAF_HOOK_MODE``:

    block (default)  exit 2 with a reason, so Claude Code stops the prompt/tool call
    warn             allow, but print a notice
    off              do nothing

Only entity types and counts are ever printed, never the values.
Requires ``pip install saaf``.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from typing import Any

from saaf import Saaf


def _texts(event: dict[str, Any], kind: str) -> list[str]:
    if kind == "prompt":
        return [str(event.get("prompt", ""))]
    tool_input = event.get("tool_input") or {}
    return [v for k, v in tool_input.items() if isinstance(v, str) and k in ("content", "new_string", "command")]


def main(argv: list[str]) -> int:
    kind = argv[1] if len(argv) > 1 else "prompt"
    mode = os.environ.get("SAAF_HOOK_MODE", "block")
    if mode == "off":
        return 0
    event = json.load(sys.stdin)
    saaf = Saaf()
    counts: Counter[str] = Counter()
    for text in _texts(event, kind):
        counts.update(f.entity for f in saaf.scan(text))
    if not counts:
        return 0
    summary = ", ".join(f"{n} x {e}" for e, n in sorted(counts.items()))
    where = "prompt" if kind == "prompt" else f"{event.get('tool_name', 'tool')} input"
    message = f"Saaf: personal data detected in {where} ({summary}). Remove or mask it before sending."
    if mode == "warn":
        print(message, file=sys.stderr)
        return 0
    print(message, file=sys.stderr)
    return 2  # Claude Code: block and show stderr to the user / model


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
