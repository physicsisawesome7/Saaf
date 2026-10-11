from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from saaf import Policy
from saaf.policy import EntityPolicy
from saaf_litellm import SaafBlockedError, SaafGuardrail

PAN = "ABCPE1234F"


async def test_round_trip() -> None:
    g = SaafGuardrail()
    data = {"litellm_call_id": "c1", "model": "gpt", "messages": [{"role": "user", "content": f"PAN {PAN}"}]}
    data = await g.async_pre_call_hook(None, None, data, "completion")
    assert data["messages"][0]["content"] == "PAN [PAN_1]"
    tc = NS(function=NS(arguments='{"pan": "[PAN_1]"}'))
    resp = NS(choices=[NS(message=NS(content="ok [PAN_1]", tool_calls=[tc]))])
    resp = await g.async_post_call_success_hook(data, None, resp)
    assert resp.choices[0].message.content == f"ok {PAN}"
    assert tc.function.arguments == f'{{"pan": "{PAN}"}}'
    assert g._sessions == {}


async def test_streaming() -> None:
    g = SaafGuardrail()
    data = {"litellm_call_id": "c2", "messages": [{"role": "user", "content": f"PAN {PAN}"}]}
    await g.async_pre_call_hook(None, None, data, "completion")

    async def upstream():
        for text, finish in (("got [PA", None), ("N_1", None), ("] done", "stop")):
            yield NS(choices=[NS(index=0, delta=NS(content=text), finish_reason=finish)])

    out = [c.choices[0].delta.content async for c in g.async_post_call_streaming_iterator_hook(None, upstream(), data)]
    assert "".join(out) == f"got {PAN} done"


async def test_block() -> None:
    g = SaafGuardrail(Policy(entities={"PAN": EntityPolicy(action="block")}))
    with pytest.raises(SaafBlockedError):
        await g.async_pre_call_hook(
            None, None, {"litellm_call_id": "c3", "messages": [{"role": "user", "content": PAN}]}, "completion"
        )
