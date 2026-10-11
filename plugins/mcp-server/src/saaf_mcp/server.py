"""Saaf MCP server (stdio).

Gives any MCP client -- Claude Desktop, Claude Code, IDE agents -- tools to
check and sanitize text before it is pasted, logged or sent elsewhere:

    saaf_scan      entity types, positions and scores (never values)
    saaf_mask      mask text; tokens are kept in a named in-memory session
    saaf_restore   restore tokens from a session
    saaf_entities  list supported entity types

Register with Claude Code::

    claude mcp add saaf -- saaf-mcp
"""

# No `from __future__ import annotations`: FastMCP inspects real annotations.

import os
from collections import OrderedDict
from typing import Any

from mcp.server.fastmcp import FastMCP

from saaf import Policy, Saaf, default_spec

mcp = FastMCP("saaf")
_POLICY = Policy.load(p) if (p := os.environ.get("SAAF_POLICY")) else Policy()
_SESSIONS: OrderedDict[str, Saaf] = OrderedDict()
MAX_SESSIONS = 256


def _session(name: str) -> Saaf:
    if name not in _SESSIONS:
        _SESSIONS[name] = Saaf(_POLICY)
        while len(_SESSIONS) > MAX_SESSIONS:
            _SESSIONS.popitem(last=False)
    _SESSIONS.move_to_end(name)
    return _SESSIONS[name]


@mcp.tool()
def saaf_scan(text: str) -> dict[str, Any]:
    """Detect Indian PII (Aadhaar, PAN, GSTIN, UPI, mobile, cards, ...) in text.
    Returns entity types, character offsets and confidence scores, never the values."""
    findings = Saaf(_POLICY).scan(text)
    return {"count": len(findings), "findings": [f.to_dict() for f in findings]}


@mcp.tool()
def saaf_mask(text: str, session: str = "default") -> dict[str, Any]:
    """Replace PII in text with tokens such as [AADHAAR_1]. Use the same
    `session` with saaf_restore to put the values back later."""
    r = _session(session).mask(text)
    if r.blocked:
        return {"blocked": True, "summary": r.summary()}
    return {"text": r.text, "summary": r.summary()}


@mcp.tool()
def saaf_restore(text: str, session: str = "default") -> dict[str, Any]:
    """Restore tokens produced by saaf_mask in the same session."""
    r = _session(session).restore(text)
    return {"text": r.text, "restored": r.restored, "unknown_tokens": r.unknown}


@mcp.tool()
def saaf_entities() -> list[dict[str, str]]:
    """List the entity types Saaf detects."""
    return [{"id": e.id, "label": e.label, "severity": e.severity} for e in default_spec().entities]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
