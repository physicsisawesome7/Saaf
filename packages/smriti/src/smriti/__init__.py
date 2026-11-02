"""Smriti by Safearly: permission-aware institutional memory.

Crawls an organisation's documents and the sites it depends on, keeps them
fresh and versioned, and answers questions with verified citations. Every
heavy component (vector store, embedder, reranker, LLM, blob store,
authoriser) sits behind an interface so a pilot runs on one laptop and a
production install runs on Postgres, Qdrant and vLLM with the same code.
"""

__version__ = "0.1.0"
