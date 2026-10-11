from __future__ import annotations

import random

import pytest
from conftest import AADHAAR, PAN

from saaf import Policy, Saaf


def _session() -> tuple[Saaf, str]:
    v = Saaf()
    masked = v.mask(f"Aadhaar {AADHAAR} and PAN {PAN}").text
    return v, masked


def _run(v: Saaf, chunks: list[str]) -> str:
    s = v.stream_restorer()
    return "".join(s.feed(c) for c in chunks) + s.flush()


@pytest.mark.parametrize("seed", range(25))
def test_any_chunking_restores_fully(seed: int) -> None:
    v, _ = _session()
    output = "Verified [AADHAAR_1]. PAN_1 matches; see **\\[PAN_1\\]** and [aadhaar_1]'s record."
    rng = random.Random(seed)
    chunks, i = [], 0
    while i < len(output):
        n = rng.randint(1, 6)
        chunks.append(output[i : i + n])
        i += n
    expected = v.restore(output).text
    assert _run(v, chunks) == expected
    assert AADHAAR in expected and PAN in expected


def test_char_by_char() -> None:
    v, _ = _session()
    out = "x [PAN_1] y"
    assert _run(v, list(out)) == f"x {PAN} y"


def test_does_not_hold_plain_text() -> None:
    v, _ = _session()
    s = v.stream_restorer()
    assert s.feed("Hello there, ") == "Hello there, "
    assert s.feed("all good.") == "all good."


def test_holds_partial_token_then_releases() -> None:
    v, _ = _session()
    s = v.stream_restorer()
    assert s.feed("id [AADH") == "id "
    assert s.feed("AAR_1] done") == f"{AADHAAR} done"


def test_no_prefix_collision_across_chunks() -> None:
    v = Saaf()
    for i in range(10):
        v.mask(f"PAN ABCPE{1000 + i}F")
    s = v.stream_restorer()
    out = s.feed("PAN_1") + s.feed("0 here") + s.flush()
    assert out == "ABCPE1009F here"


def test_unknown_token_split_is_reported_whole() -> None:
    v = Saaf(Policy(on_unknown_token="strip"))
    v.mask(f"PAN {PAN}")
    s = v.stream_restorer()
    out = s.feed("a [GST") + s.feed("IN_9] b") + s.flush()
    assert out == "a  b" and s.unknown == ["[GSTIN_9]"]


def test_fake_split_across_chunks() -> None:
    v = Saaf(Policy(token_style="fake"))
    fake = v.mask(f"aadhaar {AADHAAR}").tokens[0]
    s = v.stream_restorer()
    out = s.feed("id " + fake[:6]) + s.feed(fake[6:] + " end") + s.flush()
    assert out == f"id {AADHAAR} end"
