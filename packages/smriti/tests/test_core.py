"""Unit tests for the pieces that must never regress: access rules, masking,
chunking, versioning and the audit chain."""

from __future__ import annotations

from smriti.access import evaluate, strictest
from smriti.chunking import chunk_document
from smriti.metadata import extract, to_iso
from smriti.parsers import parse
from smriti.privacy import mask_table, mask_text
from smriti.store import audit


def test_admin_is_not_a_reader(tenant):
    admin = tenant.principal("admin")
    gcc = tenant.store.find_by_ref(tenant.id, "GCC")
    assert gcc is not None
    assert not evaluate(admin, gcc["access"], gcc["doc_type"]).allowed
    assert "administering" in evaluate(admin, gcc["access"], gcc["doc_type"]).reasons[0]


def test_scope_rules(tenant):
    asha, vikram, nadia, km = (tenant.principal(u) for u in ("asha", "vikram", "nadia", "km"))
    land = tenant.store.find_by_ref(tenant.id, "LA/P-17/SCH/2025")
    lko = tenant.store.find_by_ref(tenant.id, "NR-LKO-ENG-2025-03")
    vig = tenant.store.find_by_ref(tenant.id, "VIG/2025/12")
    assert not evaluate(asha, land["access"], land["doc_type"]).allowed  # class and project
    assert evaluate(vikram, land["access"], land["doc_type"]).allowed
    assert not evaluate(asha, lko["access"], lko["doc_type"]).allowed  # other division
    assert evaluate(vikram, lko["access"], lko["doc_type"]).allowed
    assert evaluate(nadia, vig["access"], vig["doc_type"]).allowed  # need-to-know group
    assert not evaluate(km, vig["access"], vig["doc_type"]).allowed


def test_strictest_access_for_derived_items(tenant):
    asha = tenant.principal("asha")
    public = {"doc_class": "public", "divisions": ["*"]}
    land = tenant.store.find_by_ref(tenant.id, "LA/P-17/SCH/2025")["access"]
    derived = strictest([public, land])
    assert derived.doc_class == "confidential"
    assert not evaluate(asha, derived, "memory-note").allowed


def test_access_key_differs_by_person(tenant):
    # personal memories make two people with the same role different cache keys
    assert tenant.principal("asha").access_key != tenant.principal("vikram").access_key


def test_masking_keeps_order_ids_and_masks_aadhaar_and_names():
    text, cats = mask_text("Owner: Ram Prasad, Aadhaar 2345 6789 0124. Order ID 234567890124.")
    assert "[AADHAAR]" in text and "[LAND_OWNER_NAME]" in text
    assert "234567890124" in text  # checksum-valid look-alike, but labelled as an order id
    assert {"aadhaar", "land_owner_name"} <= cats
    unmasked, _ = mask_text("Owner: Ram Prasad", unmask=["land_owner_name"])
    assert "Ram Prasad" in unmasked
    assert mask_text("list the land owner Aadhaar numbers")[1] == set()  # no name follows the label


def test_mask_table_by_column():
    rows, cats = mask_table(["Plot", "Name of owner", "Area"], [["P1", "Sita Devi", "0.2"]])
    assert rows == [["P1", "[LAND_OWNER_NAME]", "0.2"]] and cats == {"land_owner_name"}


def test_clause_chunking_and_relations():
    md = b"""# GCC\n\n## 16. Performance Guarantee\n\n16.1 Submit within 21 days.\n\n16.2 Late fee applies after Clause 16.1 of GCC.\n"""
    doc = parse(md, "gcc.md")
    meta = extract(doc.text, doc.title, {}, {})
    chunks, _ = chunk_document("gcc", doc, meta)
    assert [c.clause_id for c in chunks] == ["16.1", "16.2"]
    assert any(r["rel_type"] == "refers_to" and r["clause_id"] == "16.1" for r in meta["relations"])


def test_dates():
    assert to_iso("dated 25.09.2024") == "2024-09-25"
    assert to_iso("13 Sep 2024") == "2024-09-13"
    assert to_iso("2026-03-16") == "2026-03-16"


def test_supersession_and_parsers(tenant):
    old = tenant.store.find_by_ref(tenant.id, "BRD/2019/W1/POA")
    assert old["status"] == "superseded"
    land = tenant.store.find_by_ref(tenant.id, "LA/P-17/SCH/2025")
    assert land["meta"]["parser"] == "openpyxl"
    assert any("hidden sheet" in w for w in land["meta"]["warnings"])
    email = tenant.store.get_document(tenant.id, "contractor-letter-pg-extension")
    assert email["doc_type"] == "correspondence" and "phone_in" in email["access"]["pii"]


def test_incremental_reingest_reuses_unchanged_chunks(tenant):
    body = b"---\ntitle: Re-ingest probe\naccess: {doc_class: public}\n---\n# Probe\n\n1.1 First clause stays.\n\n1.2 Second clause stays.\n"
    a = tenant.ingest(body, "probe.md", actor="test")
    b = tenant.ingest(body.replace(b"Second clause stays", b"Second clause changed"), "probe.md", actor="test")
    assert a["version"] == 1 and b["version"] == 2
    assert b["chunks_unchanged"] == 1 and b["chunks_added"] == 1 and b["chunks_retired"] == 1
    assert tenant.ingest(body, "probe-copy.md", actor="test")["status"] == "duplicate"


def test_audit_chain_detects_tampering(tenant):
    assert tenant.audit.verify()["ok"]
    with tenant.store.engine.begin() as c:
        first = c.execute(audit.select().where(audit.c.tenant == tenant.id).order_by(audit.c.seq).limit(1)).first()
        c.execute(audit.update().where(audit.c.seq == first.seq).values(actor="someone-else"))
    v = tenant.audit.verify()
    assert not v["ok"] and v["broken_at"] == first.seq
    with tenant.store.engine.begin() as c:
        c.execute(audit.update().where(audit.c.seq == first.seq).values(actor=first.actor))
    assert tenant.audit.verify()["ok"]
