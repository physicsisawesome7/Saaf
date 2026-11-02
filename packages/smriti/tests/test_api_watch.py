"""HTTP API and the Watch loop, end to end against the app's own demo site."""

from __future__ import annotations

from fastapi.testclient import TestClient

from smriti.watch import cron_match, normalise_url, run_source


def _c(app, user):  # type: ignore[no-untyped-def]
    c = TestClient(app)
    c.headers["X-Smriti-User"] = user
    return c


def test_hidden_documents_are_not_confirmed(fresh_app):
    asha = _c(fresh_app, "asha")
    assert asha.get("/api/documents/ref-la-p-17-sch-2025").status_code == 404
    ids = {d["doc_id"] for d in asha.get("/api/documents").json()}
    assert "ref-la-p-17-sch-2025" not in ids and "ref-gcc-2022" in ids
    admin = _c(fresh_app, "admin").get("/api/documents").json()
    assert admin and not any(d["readable"] for d in admin)  # metadata only


def test_raw_download_needs_unmask_rights(fresh_app):
    assert _c(fresh_app, "vikram").get("/api/documents/ref-la-p-17-sch-2025/raw").status_code == 403
    assert _c(fresh_app, "rakesh").get("/api/documents/ref-la-p-17-sch-2025/raw").status_code == 200


def test_openai_compatible_endpoint(fresh_app):
    r = _c(fresh_app, "asha").post(
        "/v1/chat/completions",
        json={
            "model": "smriti/railways-demo",
            "messages": [{"role": "user", "content": "What is the maximum liquidated damages under clause 46.1?"}],
        },
    )
    body = r.json()
    assert r.status_code == 200
    assert "5%" in body["choices"][0]["message"]["content"]
    assert "Sources:" in body["choices"][0]["message"]["content"]


def test_watch_detects_new_slip_and_routes_impact(fresh_app):
    plat = fresh_app.state.platform
    t = plat.tenant(None)
    client = TestClient(fresh_app)  # the crawler talks to the demo site through the app itself
    first = run_source(t, "board-circulars", client=client)
    assert not first["errors"]
    assert run_source(t, "board-circulars", client=client)["unchanged"]

    km = _c(fresh_app, "km")
    assert km.post("/api/demo/publish").json()["published"]["file"] == "correction-slip-11.md"
    rep = run_source(t, "board-circulars", client=client)
    assert [e["title"] for e in rep["new"]] == ["Correction Slip No. 11 to GCC April 2022 (synthetic)"]

    asha_alerts = _c(fresh_app, "asha").get("/api/alerts").json()
    vikram_alerts = _c(fresh_app, "vikram").get("/api/alerts").json()
    asha_impact = {x["doc_id"] for x in asha_alerts[0]["impact"]}
    vikram_impact = {x["doc_id"] for x in vikram_alerts[0]["impact"]}
    assert "ref-nr-dli-eng-2025-14" in asha_impact and "ref-nr-lko-eng-2025-03" not in asha_impact
    assert "ref-nr-lko-eng-2025-03" in vikram_impact
    assert _c(fresh_app, "bidder").get("/api/alerts").json() == []

    ans = (
        _c(fresh_app, "asha")
        .post("/api/ask", json={"question": "What is the performance guarantee under clause 16.1?"})
        .json()
    )
    assert "3%" in ans["answer"] and "5%" not in ans["answer"]


def test_memory_is_private_until_approved(fresh_app):
    asha, meera, km = _c(fresh_app, "asha"), _c(fresh_app, "meera"), _c(fresh_app, "km")
    mine = asha.post("/api/memories", json={"text": "I prefer 18-month completion periods.", "tier": "user"}).json()
    assert mine["status"] == "approved"
    assert all(m["id"] != mine["id"] for m in meera.get("/api/memories").json())
    team = asha.post("/api/memories", json={"text": "Doubling works use the zone template v4.", "tier": "team"}).json()
    assert team["status"] == "proposed"
    assert asha.post(f"/api/memories/{team['id']}/review?approve=true").status_code == 403
    assert km.post(f"/api/memories/{team['id']}/review?approve=true").json()["status"] == "approved"
    assert asha.delete(f"/api/memories/{mine['id']}").json() == {"ok": True}


def test_maker_checker(fresh_app):
    meera = _c(fresh_app, "meera")
    ex = next(s for s in meera.get("/api/skills").json() if s["name"] == "validate-acceptance-letter")["example"]
    res = meera.post("/api/skills/validate-acceptance-letter/run", json=ex).json()
    did = res["draft"]["id"]
    assert res["draft"]["content"].startswith("DRAFT FOR OFFICER REVIEW")
    assert meera.post(f"/api/drafts/{did}", json={"action": "submit"}).status_code == 200
    assert meera.post(f"/api/drafts/{did}", json={"action": "approve"}).status_code == 403  # same person


def test_url_normalisation_and_cron():
    assert normalise_url("HTTP://Site.gov.in/a/b.pdf?sid=abc&x=1#top") == "http://site.gov.in/a/b.pdf?x=1"
    from datetime import datetime

    assert cron_match("0 */6 * * *", datetime(2026, 10, 30, 12, 0))
    assert not cron_match("0 */6 * * *", datetime(2026, 10, 30, 13, 0))
