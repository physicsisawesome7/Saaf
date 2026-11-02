"""MCP server: the same permission-checked tools for Claude Desktop, IDEs and
agent frameworks. The identity is fixed when the server starts, so a client
cannot ask for another person's view.

    smriti mcp --as asha
"""

from __future__ import annotations

from typing import Any


def serve_stdio(plat: Any, user: str) -> None:
    from mcp.server.fastmcp import FastMCP  # needs smriti[mcp]

    from .access import evaluate
    from .ask import ask

    t = plat.tenant(None)
    p = t.principal(user)
    mcp = FastMCP("smriti")

    @mcp.tool()
    def search_knowledge(query: str, as_of: str | None = None) -> list[dict[str, Any]]:
        """Search the institutional memory. Returns authorised, version-aware passages with citations."""
        ps, _ = t.retrieve(p, query, as_of=as_of)
        return [
            {
                "n": x.n,
                "title": x.title,
                "ref_no": x.ref_no,
                "clause": x.clause_id,
                "status": x.status,
                "doc_id": x.doc_id,
                "text": x.text,
            }
            for x in ps
        ]

    @mcp.tool()
    def ask_question(question: str, as_of: str | None = None) -> dict[str, Any]:
        """Ask a question; the answer is verified against its citations or the system abstains."""
        r = ask(t, p, question, as_of=as_of)
        return {
            "answer": r["answer"],
            "abstained": r["abstained"],
            "citations": [
                {k: c[k] for k in ("n", "title", "ref_no", "clause_id", "page", "status")} for c in r["citations"]
            ],
        }

    @mcp.tool()
    def get_document(doc_id: str) -> dict[str, Any]:
        """Fetch a document's metadata and text, if the caller may read it."""
        d = t.store.get_document(t.id, doc_id)
        if not d or not evaluate(p, d["access"], d["doc_type"]).allowed:
            return {"error": "not found"}
        chunks = t.store.doc_chunks(t.id, doc_id)
        return {
            "title": d["title"],
            "ref_no": d["ref_no"],
            "date": d["doc_date"],
            "status": d["status"],
            "text": "\n\n".join(t.render_for(p, c, d)[0] for c in chunks),
        }

    mcp.run()
