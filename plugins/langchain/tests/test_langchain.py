from __future__ import annotations

import pytest

pytest.importorskip("langchain_core")

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from saaf_langchain import mask_documents, with_saaf

PAN = "ABCPE1234F"


def test_with_saaf_masks_and_restores() -> None:
    seen = []

    def fake_model(messages, config=None):
        seen.append(messages)
        return AIMessage(
            content=f"echo: {messages[-1].content}", tool_calls=[{"name": "kyc", "args": {"pan": "[PAN_1]"}, "id": "1"}]
        )

    chain = with_saaf(RunnableLambda(fake_model))
    out = chain.invoke([HumanMessage(content=f"PAN {PAN}")])
    assert seen[0][0].content == "PAN [PAN_1]"
    assert out.content == f"echo: PAN {PAN}"
    assert out.tool_calls[0]["args"] == {"pan": PAN}


async def test_async() -> None:
    chain = with_saaf(RunnableLambda(lambda s: f"got {s}"))
    assert await chain.ainvoke(f"PAN {PAN}") == f"got PAN {PAN}"


def test_mask_documents_stable_tokens() -> None:
    key = b"k" * 32
    a = mask_documents([Document(page_content=f"PAN {PAN}")], key=key)
    b = mask_documents([Document(page_content=f"filed by {PAN}")], key=key)
    tok = a[0].page_content.removeprefix("PAN ")
    assert tok.startswith("[PAN_") and b[0].page_content.endswith(tok)
    assert a[0].metadata["saaf_entities"] == {"PAN": 1}
