"""Mask PII in your own API before your code calls an LLM.

pip install fastapi uvicorn "saaf @ git+https://github.com/physicsisawesome7/Saaf#subdirectory=packages/saaf-core"
uvicorn examples.python.fastapi_middleware:app
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from saaf import Saaf

app = FastAPI()


class Ask(BaseModel):
    question: str


def call_llm(text: str) -> str:  # replace with your model call
    return f"I received: {text}"


@app.post("/ask")
def ask(body: Ask) -> dict[str, object]:
    saaf = Saaf()  # one session per request
    masked = saaf.mask(body.question)
    if masked.blocked:
        return {"error": "blocked by data policy", "entities": masked.entity_counts}
    answer = saaf.restore(call_llm(masked.text)).text
    return {"answer": answer, "saaf": masked.summary()}
