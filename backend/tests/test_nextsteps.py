from datetime import date

import pytest

from app.database import SessionLocal
from app.models import Recommendation
from app.services import advisors, casefile, jobs, llm, nextsteps, recommendations
from tests.test_record import REPORT

ADVICE = (
    "Dr Pranav Bhatt OPD note dated 12/01/2025. Advised adjuvant radiotherapy after 3 weeks. "
    "PET scan suggested after completion. Review with CBC and LFT. Dietitian referral for swallowing."
)


@pytest.fixture
def advice_doc(client):
    return client.post("/api/documents", files={"file": ("advice.txt", ADVICE.encode(), "text/plain")}).json()


def fake_recs(items):
    return lambda system, _input, **_: {"recommendations": items}


GOOD_ITEMS = [
    {"text": "Adjuvant radiotherapy", "category": "radiotherapy", "advisor": "Dr Pranav Bhatt", "date": "2025-01-12",
     "timing": "after 3 weeks", "certainty": "advised", "quote": "Advised adjuvant radiotherapy after 3 weeks"},
    {"text": "PET scan after completion", "category": "imaging", "advisor": "Dr Pranav Bhatt", "date": "2025-01-12",
     "certainty": "suggested", "quote": "PET scan suggested after completion"},
    {"text": "Dietitian referral", "category": "referral", "advisor": "Dr Pranav Bhatt", "date": "2031-05-05",
     "certainty": "advised", "quote": "Dietitian referral for swallowing"},
    {"text": "Invented chemotherapy", "category": "chemotherapy", "quote": "Start six cycles of cisplatin immediately"},
]


def test_extraction_keeps_only_quoted_advice_and_repairs_dates(client, advice_doc, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_recs(GOOD_ITEMS))
    with SessionLocal() as db:
        from app.models import Document

        kept, rejected = recommendations.extract(db, db.get(Document, advice_doc["id"]))
    assert [k["text"] for k in kept] == ["Adjuvant radiotherapy", "PET scan after completion", "Dietitian referral"]
    assert kept[2]["rec_date"] == advice_doc["doc_date"]  # a date not found in the document falls back to the document's own date
    assert [r["item"] for r in rejected] == ["Invented chemotherapy"] and "quote not found" in rejected[0]["reason"]


def test_recommendation_dedupe_and_status_lifecycle(client):
    with SessionLocal() as db:
        a = recommendations.add(db, text="Adjuvant radiotherapy", category="radiotherapy", advisor="Dr A", rec_date="2025-01-12")
        assert a and recommendations.add(db, text="adjuvant radiotherapy", category="radiotherapy", rec_date="2025-01-12") is None
        assert recommendations.add(db, text="Adjuvant radiotherapy advised", category="radiotherapy", rec_date="") is None  # undated near-duplicate
        db.commit()
        rid = a.id
    r = client.patch(f"/api/recommendations/{rid}", json={"status": "done", "note": "Completed Feb 2025"}).json()
    assert r[0]["status"] == "done" and r[0]["note"] == "Completed Feb 2025"
    assert client.patch(f"/api/recommendations/{rid}", json={"status": "weird"}).status_code == 422
    assert client.patch("/api/recommendations/999", json={"status": "done"}).status_code == 404
    assert client.patch(f"/api/recommendations/{rid}", json={"status": "open"}).json()[0]["status"] == "open"
    assert client.delete(f"/api/recommendations/{rid}").status_code == 204 and client.get("/api/recommendations").json() == []


def test_you_can_add_advice_you_were_given_in_person(client):
    r = client.post("/api/recommendations", json={"text": "Dental review before radiotherapy", "category": "supportive", "advisor": "Dr B", "rec_date": "2025-01-05"})
    assert r.status_code == 200 and r.json()[0]["source"] == "you" and r.json()[0]["quote"] == ""
    assert client.post("/api/recommendations", json={"text": "  "}).status_code == 409


def test_later_matching_journey_event_flags_possibly_done(client):
    with SessionLocal() as db:
        recommendations.add(db, text="PET scan after surgery", category="imaging", rec_date="2025-01-12")
        recommendations.add(db, text="Adjuvant radiotherapy", category="radiotherapy", rec_date="2025-01-12")
        casefile.add_event(db, "2025-12-26", "imaging", "FDG PET-CT scan")
        casefile.add_event(db, "2024-11-01", "radiotherapy", "Earlier radiotherapy")  # before the advice: does not count
        db.commit()
    recs = {r["category"]: r for r in client.get("/api/recommendations").json()}
    assert recs["imaging"]["addressed_by"][0]["title"] == "FDG PET-CT scan"
    assert recs["radiotherapy"]["addressed_by"] == []


def test_do_next_is_ranked_by_urgency_and_explains_itself(client, monkeypatch):
    from tests.test_record import GOOD
    from tests.test_jobs import bulk, drain

    # a confirmed scan with a vascular finding gives an 'attention' item
    doc = client.post("/api/documents", files={"file": ("pet.txt", REPORT.encode(), "text/plain")}).json()
    monkeypatch.setattr(llm, "chat_json", lambda s, i, **_: GOOD)
    p = client.post(f"/api/documents/{doc['id']}/extract-scan").json()
    client.post(f"/api/documents/{doc['id']}/scan", json={
        "modality": "PET-CT", "date": p["study"]["date"], "comparator_date": p["study"]["comparator_date"], "comparator_modality": "MRI",
        "lesions": p["lesions"], "findings": p["findings"]})
    with SessionLocal() as db:
        recommendations.add(db, text="Adjuvant radiotherapy", category="radiotherapy", advisor="Dr A", rec_date="2026-10-20", timing="soon")
        recommendations.add(db, text="PET scan", category="imaging", advisor="Dr A", rec_date="2026-10-20")  # a later scan exists → possibly done
        recommendations.add(db, text="Old dental review", category="supportive", advisor="Dr B", rec_date="2024-01-05")  # stale
        done = recommendations.add(db, text="Already finished", category="supportive", rec_date="2026-10-01")
        db.commit()
        recommendations.set_status(db, done.id, "done")
        items = nextsteps.do_next(db, date(2026, 11, 11))
    titles = [i["title"] for i in items]
    assert items[0]["severity"] == "attention"  # the blood-vessel finding comes first
    assert "Already finished" not in titles  # done items leave the list
    by = {i["title"]: i for i in items}
    assert by["Adjuvant radiotherapy"]["score"] > by["Old dental review"]["score"]
    assert by["PET scan"]["possibly_done"] and by["PET scan"]["score"] < by["Adjuvant radiotherapy"]["score"]
    assert any("days ago" in n for n in by["Old dental review"]["notes"])
    assert by["Adjuvant radiotherapy"]["evidence"] == []  # advice you typed in has no document to quote
    assert [i["rank"] for i in items] == list(range(1, len(items) + 1))
    assert any(i["kind"] == "check" for i in items)
    assert all(i["detail"] for i in items)


def test_same_finding_on_several_scans_is_one_todo():
    def f(date_, quote):
        return {"kind": "finding", "title": f"Blood-vessel finding on the {date_} scan", "notes": [], "evidence": [{"quote": quote}]}
    rec = {"kind": "recommendation", "title": "Do X", "notes": [], "evidence": []}
    out = nextsteps._collapse_findings([f("2024-12-25", "a"), rec, f("2026-02-12", "b"), f("2025-12-25", "c")])
    findings = [i for i in out if i["kind"] == "finding"]
    assert len(findings) == 1 and rec in out
    assert "2026-02-12" in findings[0]["title"]
    assert "2024-12-25" in findings[0]["notes"][0] and "2025-12-25" in findings[0]["notes"][0]


def test_recommendations_are_found_in_the_background_for_new_documents(client, monkeypatch):
    from tests.test_jobs import bulk, drain

    monkeypatch.setattr(llm, "chat_json", lambda s, i, **_: {"recommendations": GOOD_ITEMS[:2]} if "recommendations" in s else {})
    bulk(client, [("advice.txt", ADVICE.encode())])
    drain()
    texts = [r["text"] for r in client.get("/api/recommendations").json()]
    assert texts and "Adjuvant radiotherapy" in texts
    assert client.post("/api/recommendations/rebuild").json()["queued"] == 1


def test_chat_context_lists_open_recommendations_with_tags(client, monkeypatch):
    with SessionLocal() as db:
        rec = recommendations.add(db, text="Adjuvant radiotherapy", category="radiotherapy", advisor="Dr A", rec_date="2025-01-12", timing="after 3 weeks")
        db.commit()
        tag = f"[R{rec.id}]"
    seen = {}
    monkeypatch.setattr(llm, "chat", lambda s, i, **_: seen.setdefault("i", i) or "ok")
    client.post("/api/chat", json={"message": "What did the doctors recommend?"})
    assert tag in seen["i"] and "after 3 weeks" in seen["i"]
