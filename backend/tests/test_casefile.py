import pytest

from app.database import SessionLocal
from app.models import Case, CaseEntry
from app.services import casefile, llm
from tests.test_record import REPORT


def upload(client, name, body):
    return client.post("/api/documents", files={"file": (name, body.encode(), "text/plain")}).json()


def apply(client, doc, as_of, fields, events=()):
    r = client.post("/api/case/apply", json={"document_id": doc["id"], "as_of": as_of, "fields": fields, "events": list(events)})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def docs(client):
    old = upload(client, "histo.txt", "Histopathology 23-12-2024. Biopsy from left lateral border of tongue. Invasive squamous cell carcinoma, well differentiated.")
    new = upload(client, "pet.txt", REPORT)
    return old, new


def current(client):
    return client.get("/api/case").json()


def test_old_report_never_overrides_newer_information(client, docs):
    old, new = docs
    apply(client, new, "2026-11-02", {"current_status": "Partial response on PET-CT", "diagnosis": "Recurrent carcinoma of tongue (appears)"})
    apply(client, old, "2024-12-24", {"current_status": "Biopsy: invasive squamous cell carcinoma", "diagnosis": "Invasive squamous cell carcinoma", "histology": "Squamous cell carcinoma, well differentiated"})
    cur = current(client)
    assert cur["current_status"] == "Partial response on PET-CT"  # not replaced by the 2024 report
    assert cur["diagnosis"] == "Recurrent carcinoma of tongue (appears)"
    assert cur["histology"] == "Squamous cell carcinoma, well differentiated"  # nothing newer, so the old report fills it
    detail = client.get("/api/case/detail").json()["fields"]["current_status"]
    assert [(h["as_of"], h["is_current"]) for h in detail["history"]] == [("2026-11-02", True), ("2024-12-24", False)]


def test_newer_report_becomes_current_regardless_of_upload_order(client, docs):
    old, new = docs
    apply(client, old, "2024-12-24", {"stage": "Stage II"})
    apply(client, new, "2026-11-02", {"stage": "Stage IV"})
    assert current(client)["stage"] == "Stage IV"


def test_undated_entry_never_beats_a_dated_one_but_can_fill_a_gap(client, docs):
    old, new = docs
    apply(client, new, "2026-11-02", {"stage": "Stage IV"})
    apply(client, old, "", {"stage": "Stage I", "histology": "Squamous cell carcinoma"})
    cur = current(client)
    assert cur["stage"] == "Stage IV" and cur["histology"] == "Squamous cell carcinoma"


def test_your_edit_is_dated_today_and_records_only_changes(client, docs):
    old, new = docs
    apply(client, new, "2026-11-02", {"stage": "Stage IV", "diagnosis": "Carcinoma of tongue"})
    r = client.put("/api/case", json={"stage": "Stage IV", "diagnosis": "Carcinoma of tongue", "age": "65"}).json()
    assert r["age"] == "65"
    events = [e for e in client.get("/api/timeline").json() if e["title"] == "Case file updated"]
    assert len(events) == 1 and "age" in events[0]["detail"] and "stage" not in events[0]["detail"]
    client.put("/api/case", json={"age": "65"})  # no change
    assert len([e for e in client.get("/api/timeline").json() if e["title"] == "Case file updated"]) == 1
    # a document dated after your edit supersedes it; one dated before cannot
    apply(client, old, "2024-12-24", {"age": "63"})
    assert current(client)["age"] == "65"
    apply(client, new, "2999-01-01", {"age": "70"})
    assert current(client)["age"] == "70"


def test_cumulative_fields_are_combined_oldest_first_and_not_form_editable(client, docs):
    old, new = docs
    apply(client, new, "2026-11-02", {"treatment_history": "Chemo-radiotherapy and immunotherapy completed"})
    apply(client, old, "2024-12-24", {"treatment_history": "Biopsy taken"})
    assert current(client)["treatment_history"] == "2024-12-24: Biopsy taken\n2026-11-02: Chemo-radiotherapy and immunotherapy completed"
    client.put("/api/case", json={"treatment_history": "overwrite attempt"})
    assert "overwrite" not in current(client)["treatment_history"]
    r = client.post("/api/case/entries", json={"field": "treatment_history", "value": "Adjuvant RT referral", "as_of": "2025-01-12"})
    assert r.status_code == 200
    assert current(client)["treatment_history"].splitlines()[1] == "2025-01-12: Adjuvant RT referral"


def test_events_form_a_deduplicated_chronological_journey(client, docs):
    old, new = docs
    ev = lambda d, t, q: {"date": d, "category": "imaging" if "PET" in t else "biopsy", "title": t, "quote": q}
    apply(client, new, "2026-11-02", {}, [ev("2026-11-02", "FDG PET-CT", "18 F-FDG WHOLE BODY PET-CT STUDY")])
    apply(client, old, "2024-12-24", {}, [ev("2024-12-23", "Biopsy of tongue lesion", "Biopsy from left lateral border of tongue")])
    apply(client, old, "2024-12-24", {}, [ev("2024-12-23", "biopsy of tongue lesion", "Biopsy from left lateral border of tongue")])  # duplicate
    events = client.get("/api/case/detail").json()["events"]
    assert [(e["date"], e["title"]) for e in events] == [("2024-12-23", "Biopsy of tongue lesion"), ("2026-11-02", "FDG PET-CT")]
    assert client.delete(f"/api/case/events/{events[0]['id']}").status_code == 204
    assert len(client.get("/api/case/detail").json()["events"]) == 1


def test_apply_rejects_event_quote_not_in_document(client, docs):
    _, new = docs
    r = client.post("/api/case/apply", json={"document_id": new["id"], "as_of": "2026-11-02", "fields": {},
                    "events": [{"date": "2026-11-02", "category": "surgery", "title": "Surgery", "quote": "Patient underwent a wide local excision"}]})
    assert r.status_code == 422


def test_extraction_validates_events_and_keeps_date_context(client, docs, monkeypatch):
    old, _ = docs
    monkeypatch.setattr(llm, "chat_json", lambda s, i, **_: {
        "fields": {"diagnosis": "Invasive squamous cell carcinoma"},
        "events": [
            {"date": "2024-12-23", "category": "biopsy", "title": "Biopsy", "quote": "Biopsy from left lateral border of tongue"},
            {"date": "2019-01-01", "category": "surgery", "title": "Old surgery", "quote": "Biopsy from left lateral border of tongue"},
            {"date": "2024-12-23", "category": "chemotherapy", "title": "Chemo", "quote": "Patient received six cycles of cisplatin chemotherapy"},
        ]})
    r = client.post(f"/api/documents/{old['id']}/extract-case").json()
    assert r["proposed"]["diagnosis"] == "Invasive squamous cell carcinoma" and r["as_of"] == "2024-12-23"
    assert [(e["title"], e["date"]) for e in r["events"]] == [("Biopsy", "2024-12-23"), ("Old surgery", "")]  # unseen date dropped, event kept
    reasons = " | ".join(x["reason"] for x in r["rejected"])
    assert "quote not found" in reasons and "date not found" in reasons


def test_legacy_flat_case_file_is_migrated_into_history(client):
    with SessionLocal() as db:
        db.add(Case(id=1, diagnosis="Carcinoma of tongue", stage="Stage IV", treatment_history="Surgery then RT"))
        db.commit()
        assert db.query(CaseEntry).count() == 0
    assert casefile.migrate_legacy() == 3
    assert casefile.migrate_legacy() == 0  # idempotent
    cur = current(client)
    assert cur["diagnosis"] == "Carcinoma of tongue" and cur["stage"] == "Stage IV" and cur["treatment_history"].endswith("Surgery then RT")
    assert client.get("/api/case/detail").json()["fields"]["stage"]["source"] == "you"
    assert client.get("/api/case/detail").json()["fields"]["stage"]["as_of"] == ""  # date unknown, not "today"


def test_migrated_undated_values_yield_to_any_dated_report_and_can_be_dated(client, docs):
    _, new = docs
    with SessionLocal() as db:
        db.add(Case(id=1, current_status="Old status typed before history existed"))
        db.commit()
    casefile.migrate_legacy()
    apply(client, new, "2026-11-02", {"current_status": "Partial response on PET-CT"})
    assert current(client)["current_status"] == "Partial response on PET-CT"
    entry = next(h for h in client.get("/api/case/detail").json()["fields"]["current_status"]["history"] if h["source"] == "you")
    r = client.patch(f"/api/case/entries/{entry['id']}", json={"as_of": "2027-01-01"})
    assert r.status_code == 200 and current(client)["current_status"] == "Old status typed before history existed"
    assert client.patch(f"/api/case/entries/{entry['id']}", json={"as_of": "not-a-date"}).status_code == 422


def test_summary_goes_stale_when_history_changes_and_rejects_unsafe_text(client, docs, monkeypatch):
    old, new = docs
    apply(client, new, "2026-11-02", {"current_status": "Partial response on PET-CT"})
    seen = {}
    monkeypatch.setattr(llm, "chat", lambda s, i, **_: seen.setdefault("i", i) and "In 2026 a PET-CT reported a partial response.")
    s = client.post("/api/case/summary").json()
    assert s["text"].startswith("In 2026") and s["stale"] is False
    assert "Partial response on PET-CT" in seen["i"] and "as of 2026-11-02" in seen["i"]
    apply(client, old, "2024-12-24", {"histology": "Squamous cell carcinoma"})
    assert client.get("/api/case/detail").json()["summary"]["stale"] is True
    monkeypatch.setattr(llm, "chat", lambda s, i, **_: "You should stop chemotherapy now.")
    assert client.post("/api/case/summary").status_code == 502


def test_chat_context_separates_current_from_superseded_history(client, docs, monkeypatch):
    old, new = docs
    apply(client, new, "2026-11-02", {"current_status": "Partial response on PET-CT"}, [{"date": "2026-11-02", "category": "imaging", "title": "FDG PET-CT", "quote": "18 F-FDG WHOLE BODY PET-CT STUDY"}])
    apply(client, old, "2024-12-24", {"current_status": "Biopsy: invasive squamous cell carcinoma"})
    seen = {}
    monkeypatch.setattr(llm, "chat", lambda s, i, **_: seen.setdefault("i", i) or "ok")
    client.post("/api/chat", json={"message": "What is the current status?"})
    text = seen["i"]
    assert "- Current status: Partial response on PET-CT" in text
    assert "Current status as of 2024-12-24: Biopsy: invasive squamous cell carcinoma (superseded)" in text
    assert "2026-11-02 [imaging] FDG PET-CT" in text
