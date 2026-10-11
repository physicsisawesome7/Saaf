"""Property-based tests for the invariants the plan depends on."""

from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from saaf import Saaf
from saaf.normalize import normalize

FRAGMENTS = [
    "Aadhaar 2345 6789 0124",
    "aadhar २३४५ ६७८९ ०१२४",
    "uid 2345​6789​0124",
    "PAN ABCPE1234F",
    "pan АВСРЕ1234F",
    "GSTIN 27ABCPE1234F1ZB",
    "mobile +91 98765 43210",
    "UPI ravi@okaxis",
    "mail ravi.k@example.co.in",
    "card 4111 1111 1111 1111",
    "order 234567890124",
    "Smt. Lakshmi Iyer",
    "hello",
    "kya haal hai",
    "invoice INV-2024-000123",
    "12",
    "😀",
    "\n",
    ", ",
    ". ",
]

texts = st.lists(st.sampled_from(FRAGMENTS), min_size=1, max_size=12).map(" ".join)
fast = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@fast
@given(texts)
def test_mask_then_restore_is_equivalent(text: str) -> None:
    """Restore returns each value's *first-seen surface form*: one Aadhaar
    written in ASCII and in Devanagari digits shares a token, so both come back
    as the first spelling. The text is therefore equivalent rather than
    byte-identical: same skeleton, same values."""
    v = Saaf()
    restored = v.restore(v.mask(text).text).text
    assert Saaf().mask(restored).text == Saaf().mask(text).text
    assert [(f.entity, f.canonical) for f in Saaf().scan(restored)] == [
        (f.entity, f.canonical) for f in Saaf().scan(text)
    ]


@fast
@given(st.lists(st.sampled_from(FRAGMENTS[:12]), min_size=1, max_size=12, unique=True).map(" ".join))
def test_mask_then_restore_is_identity_for_distinct_values(text: str) -> None:
    # Same values in different spellings: Aadhaar in fragments 0-2 and 10 (the
    # "order" number reuses its digits), PAN in fragments 3-4.
    same_aadhaar = [FRAGMENTS[i] for i in (0, 1, 2, 10)]
    if sum(f in text for f in same_aadhaar) > 1 or sum(f in text for f in FRAGMENTS[3:5]) > 1:
        return
    v = Saaf()
    assert v.restore(v.mask(text).text).text == text


@fast
@given(texts)
def test_findings_are_valid_original_spans(text: str) -> None:
    findings = Saaf().scan(text)
    last_end = 0
    for f in findings:
        assert 0 <= f.start < f.end <= len(text)
        assert f.start >= last_end  # sorted, non-overlapping
        assert text[f.start : f.end] == f.text
        last_end = f.end


@fast
@given(texts, st.lists(st.integers(min_value=1, max_value=9), min_size=1, max_size=40))
def test_streaming_equals_batch_for_any_chunking(text: str, sizes: list[int]) -> None:
    v = Saaf()
    masked = v.mask(text).text
    reply = f"Sure. {masked} -- and again {masked.lower()}"
    expected = v.restore(reply).text
    s = v.stream_restorer()
    out, i, k = [], 0, 0
    while i < len(reply):
        n = sizes[k % len(sizes)]
        out.append(s.feed(reply[i : i + n]))
        i += n
        k += 1
    out.append(s.flush())
    assert "".join(out) == expected


@fast
@given(st.text(max_size=200))
def test_normalize_offset_map_is_monotonic_and_in_bounds(text: str) -> None:
    n = normalize(text)
    assert len(n.index_map) == len(n.text)
    assert all(0 <= i < len(text) for i in n.index_map)
    assert list(n.index_map) == sorted(n.index_map)


@fast
@given(st.text(max_size=300))
def test_never_crashes_on_arbitrary_text(text: str) -> None:
    v = Saaf()
    r = v.mask(text)
    v.restore(r.text)
