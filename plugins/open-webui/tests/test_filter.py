from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "saaf-core" / "src"))

from saaf_filter import Filter

PAN = "ABCPE1234F"


def test_inlet_outlet_round_trip() -> None:
    f = Filter()
    body = {"chat_id": "c1", "messages": [{"role": "user", "content": f"PAN {PAN}"}]}
    out = f.inlet(body)
    assert out["messages"][0]["content"] == "PAN [PAN_1]"
    reply = {"chat_id": "c1", "messages": [*out["messages"], {"role": "assistant", "content": "Your [PAN_1] is valid"}]}
    assert f.outlet(reply)["messages"][-1]["content"] == f"Your {PAN} is valid"


def test_chats_isolated() -> None:
    f = Filter()
    f.inlet({"chat_id": "a", "messages": [{"role": "user", "content": f"PAN {PAN}"}]})
    other = f.outlet({"chat_id": "b", "messages": [{"role": "assistant", "content": "[PAN_1]"}]})
    assert other["messages"][0]["content"] == "[PAN_1]"


def test_block_valve() -> None:
    f = Filter()
    f.valves.block_entities = "pan"
    with pytest.raises(Exception, match="PAN"):
        f.inlet({"chat_id": "c", "messages": [{"role": "user", "content": PAN}]})
