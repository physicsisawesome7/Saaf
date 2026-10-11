from __future__ import annotations

import json

import pytest
from conftest import AADHAAR, AADHAAR_2, GSTIN, MOBILE, PAN

from saaf import AuditLogger, MemorySink, Policy, Rule, Saaf, SaafBlocked
from saaf.policy import EntityPolicy, PolicyError
from saaf.validators import aadhaar


def test_mask_and_restore_round_trip(kyc_text: str) -> None:
    v = Saaf()
    r = v.mask(kyc_text)
    for raw in (AADHAAR, PAN, GSTIN, MOBILE, "ravi.kumar@okaxis", "ravi@example.in"):
        assert raw not in r.text
    assert v.restore(r.text).text == kyc_text
    assert r.entity_counts == {"AADHAAR": 1, "PAN": 1, "GSTIN": 1, "PHONE_IN": 1, "UPI_ID": 1, "EMAIL": 1}


def test_same_value_same_token_within_session() -> None:
    v = Saaf()
    a = v.mask(f"Aadhaar {AADHAAR}").text
    b = v.mask(f"again aadhaar {AADHAAR.replace(' ', '-')}").text
    assert a.endswith("[AADHAAR_1]") and b.endswith("[AADHAAR_1]")
    c = v.mask(f"other aadhaar {AADHAAR_2}").text
    assert c.endswith("[AADHAAR_2]")


def test_sessions_are_isolated() -> None:
    a, b = Saaf(), Saaf()
    a.mask(f"PAN {PAN}")
    assert b.restore("[PAN_1]").text == "[PAN_1]"


def test_summary_has_no_raw_values(kyc_text: str) -> None:
    blob = json.dumps(Saaf().mask(kyc_text).summary())
    for raw in (AADHAAR, PAN, "ravi"):
        assert raw not in blob


def test_shadow_mode_changes_nothing(kyc_text: str) -> None:
    v = Saaf(Policy(mode="shadow"))
    r = v.mask(kyc_text)
    assert r.text == kyc_text and r.shadow and not r.changed
    assert len(r.applied) == 6 and all(a.action == "mask" for a in r.applied)
    assert len(v.vault) == 0


def test_block_action() -> None:
    v = Saaf(Policy(entities={"AADHAAR": EntityPolicy(action="block")}))
    r = v.mask(f"aadhaar {AADHAAR} pan {PAN}")
    assert r.blocked and r.text == r.original_text
    with pytest.raises(SaafBlocked) as exc:
        v.mask(f"aadhaar {AADHAAR}", raise_on_block=True)
    assert exc.value.entities == ["AADHAAR"]


def test_warn_and_allow_leave_text() -> None:
    v = Saaf(Policy(entities={"PAN": EntityPolicy(action="warn"), "EMAIL": EntityPolicy(action="allow")}))
    text = f"PAN {PAN} mail a@b.co"
    r = v.mask(text)
    assert r.text == text
    assert {a.action for a in r.applied} == {"warn", "allow"}


def test_hash_action_is_irreversible_and_stable() -> None:
    key = b"k" * 32
    v = Saaf(Policy(default_action="hash"), hmac_key=key)
    t1 = v.mask(f"PAN {PAN}").text
    t2 = Saaf(Policy(default_action="hash"), hmac_key=key).mask(f"PAN {PAN}").text
    assert t1 == t2 and t1.startswith("PAN [PAN#")
    assert v.restore(t1).text == t1


def test_destination_rule() -> None:
    policy = Policy(rules=(Rule(action="allow", entities=("AADHAAR",), destinations=("*.in-region.example",)),))
    v = Saaf(policy)
    assert AADHAAR in v.mask(f"aadhaar {AADHAAR}", destination="llm.in-region.example").text
    assert AADHAAR not in v.mask(f"aadhaar {AADHAAR}", destination="api.openai.com").text


def test_hmac_tokens_deterministic_across_sessions() -> None:
    key = b"t" * 32
    a = Saaf(Policy(token_style="hmac"), hmac_key=key).mask(f"PAN {PAN}").text
    b = Saaf(Policy(token_style="hmac"), hmac_key=key).mask(f"PAN {PAN}").text
    assert a == b and a != "PAN [PAN_1]"


def test_fake_tokens_are_valid_but_unreal() -> None:
    v = Saaf(Policy(token_style="fake"))
    r = v.mask(f"Aadhaar {AADHAAR}, PAN {PAN}")
    fake = r.tokens[0]
    digits = fake.replace(" ", "")
    assert len(digits) == 12 and digits[0] == "1"  # starts with 1: never issued
    assert not aadhaar(digits)
    assert fake.count(" ") == 2  # grouping preserved
    assert "[PAN_1]" in r.text  # no faker for PAN -> label
    assert v.restore(f"Your ID {digits[:4]}-{digits[4:8]}-{digits[8:]} ok").text == f"Your ID {AADHAAR} ok"


def test_fake_mobile_keeps_prefix() -> None:
    v = Saaf(Policy(token_style="fake"))
    fake = v.mask(f"call {MOBILE}").tokens[0]
    assert fake.startswith("+91 5") and len(fake) == len(MOBILE)
    assert v.restore(f"ring {fake}").text == f"ring {MOBILE}"


def test_mask_messages_handles_parts() -> None:
    v = Saaf()
    msgs = [
        {"role": "system", "content": "be nice"},
        {"role": "user", "content": [{"type": "text", "text": f"PAN {PAN}"}, {"type": "image_url", "image_url": {}}]},
    ]
    out, results = v.mask_messages(msgs)
    assert out[1]["content"][0]["text"] == "PAN [PAN_1]"
    assert out[1]["content"][1] == {"type": "image_url", "image_url": {}}
    assert msgs[1]["content"][0]["text"] == f"PAN {PAN}"  # input untouched
    assert len(results) == 2


def test_mask_json_field_aware() -> None:
    v = Saaf()
    data = {"name": "x", "kyc": {"pan": PAN, "note": f"aadhaar {AADHAAR}"}, "ids": [PAN]}
    only_pan = v.mask_json(data, fields={"pan"})
    assert only_pan["kyc"]["pan"] == "[PAN_1]" and AADHAAR in only_pan["kyc"]["note"] and only_pan["ids"] == [PAN]
    everything = v.mask_json(data)
    assert everything["ids"] == ["[PAN_1]"] and AADHAAR not in everything["kyc"]["note"]


def test_restore_json_tool_call_arguments() -> None:
    v = Saaf()
    v.mask(f"PAN {PAN}")
    call = {"name": "lookup", "arguments": json.dumps({"pan": "[PAN_1]", "note": 'he said "PAN_1"'})}
    restored = v.restore_json(call)
    args = json.loads(restored["arguments"])
    assert args == {"pan": PAN, "note": f'he said "{PAN}"'}


def test_restore_reports_missing_and_unknown() -> None:
    v = Saaf(Policy(on_unknown_token="strip"))
    r = v.mask(f"PAN {PAN} aadhaar {AADHAAR}")
    out = v.restore("only [PAN_1] and [GSTIN_4]", expected=r.tokens)
    assert out.text == f"only {PAN} and "
    assert out.missing == ["[AADHAAR_1]"] and out.unknown == ["[GSTIN_4]"]


def test_flag_unknown_tokens() -> None:
    v = Saaf(Policy(on_unknown_token="flag"))
    assert v.restore("x [PAN_3]").text == "x [UNVERIFIED PAN_3]"


def test_per_entity_threshold() -> None:
    strict = Saaf(Policy(entities={"AADHAAR": EntityPolicy(threshold=0.9)}))
    assert strict.mask("number 987654321012").text == "number 987654321012"
    assert strict.mask("aadhaar 987654321012").text == "aadhaar [AADHAAR_1]"


def test_enabled_entities() -> None:
    v = Saaf(Policy(enabled_entities=("PAN",)))
    assert v.mask(f"PAN {PAN} aadhaar {AADHAAR}").text == f"PAN [PAN_1] aadhaar {AADHAAR}"


def test_audit_records_counts_only() -> None:
    sink = MemorySink()
    v = Saaf(audit=AuditLogger(sink, b"a" * 32))
    v.mask(f"aadhaar {AADHAAR}", destination="api.example")
    rec = sink[0]
    assert rec["entity_counts"] == {"AADHAAR": 1} and rec["destination"] == "api.example"
    assert AADHAAR not in json.dumps(rec)


def test_cross_turn_detection() -> None:
    v = Saaf(cross_turn=True)
    first = v.mask("my aadhaar starts 2345")
    assert first.text == "my aadhaar starts 2345"
    second = v.mask("the rest is 6789 0124")
    assert second.text == "the rest is [AADHAAR_1] [AADHAAR_2]" or "6789" not in second.text
    assert second.prior_leak


def test_policy_validation() -> None:
    with pytest.raises(PolicyError):
        Policy(mode="loud")  # type: ignore[arg-type]
    with pytest.raises(PolicyError):
        Policy.from_dict({"policy": {"nonsense": 1}})


def test_policy_toml(tmp_path) -> None:
    p = tmp_path / "policy.toml"
    p.write_text(
        '[policy]\nid = "bfsi"\nmode = "shadow"\n\n[entities.IFSC]\naction = "allow"\n\n'
        '[[rules]]\nentities = ["AADHAAR"]\ndestinations = ["*.internal"]\naction = "allow"\n',
        encoding="utf-8",
    )
    pol = Policy.load(p)
    assert pol.id == "bfsi" and pol.shadow
    assert pol.decide("IFSC") == "allow"
    assert pol.decide("AADHAAR", destination="llm.internal") == "allow"
    assert pol.decide("AADHAAR", destination="x.com") == "mask"
    assert Policy.from_dict(pol.to_dict()).fingerprint == pol.fingerprint
