import pytest

from app.database import SessionLocal
from app.models import ClinicalEvent
from app.services import casefile, jobs
from tests.test_record import REPORT


@pytest.mark.parametrize("title,given,expected", [
    ("Histopathology diagnosis", "lab", "diagnosis"),
    ("Cytology impression", "lab", "diagnosis"),
    ("USG guided FNAC", "lab", "biopsy"),
    ("Tongue lesion biopsy", "other", "biopsy"),
    ("Wide excision and neck dissection", "other", "surgery"),
    ("Left tongue carcinoma surgery", "other", "surgery"),
    ("Pre-operative physician consultation", "consultation", "consultation"),  # 'operative' is not surgery
    ("Adjuvant radiotherapy advised", "consultation", "radiotherapy"),
    ("Chest X-ray", "other", "imaging"),
    ("Hepatitis C Virus Test", "other", "lab"),
    ("Something unclear", "other", "other"),
])
def test_categorize(title, given, expected):
    assert casefile.categorize(title, "", given) == expected


def test_detail_text_does_not_change_category():
    assert casefile.categorize("Wide excision and neck dissection", "Specimen collected for histopathology review.", "surgery") == "surgery"


def add(db, d, cat, title, **kw):
    return casefile.add_event(db, d, cat, title, **kw)


@pytest.fixture
def journey(client):
    with SessionLocal() as db:
        add(db, "2024-11-26", "consultation", "Pre-operative physician consultation")
        add(db, "2024-12-23", "biopsy", "Tongue lesion biopsy")
        for t in ("Complete Blood Count", "Blood Group", "Biochemistry Report"):
            add(db, "2024-12-25", "lab", t)
        add(db, "2025-01-09", "surgery", "Wide excision and neck dissection")
        add(db, "2025-01-11", "diagnosis", "Histopathology report")
        add(db, "2025-01-12", "radiotherapy", "Adjuvant radiotherapy advised")
        add(db, "2025-12-26", "imaging", "PET-CT")
        add(db, "2026-11-02", "imaging", "FDG PET-CT follow-up")
        add(db, "", "other", "Advised review")
        db.commit()
    return client.get("/api/case/detail").json()["journey"]


def test_events_are_ordered_into_phases(journey):
    phases = {p["id"]: p for p in journey["phases"]}
    assert [p["kind"] for p in journey["phases"]] == ["workup", "treatment", "followup"]
    assert [p["id"] for p in journey["phases"]] == ["workup", "treatment-1", "followup-1"]
    assert [i["title"] for i in phases["treatment-1"]["items"]] == ["Wide excision and neck dissection", "Histopathology report", "Adjuvant radiotherapy advised"]
    assert phases["treatment-1"]["title"] == "Treatment" and phases["treatment-1"]["subtitle"] == "surgery, radiotherapy"
    assert [i["title"] for i in phases["followup-1"]["items"]] == ["PET-CT", "FDG PET-CT follow-up"]
    assert phases["workup"]["start"] == "2024-11-26" and phases["followup-1"]["end"] == "2026-11-02"


def test_a_recurrence_workup_between_two_treatments_is_not_hidden_inside_the_first(client):
    with SessionLocal() as db:
        add(db, "2024-12-23", "biopsy", "Tongue lesion biopsy")
        add(db, "2024-12-27", "surgery", "Glossectomy and neck dissection")
        add(db, "2025-01-12", "radiotherapy", "Adjuvant radiotherapy advised")
        add(db, "2025-12-26", "imaging", "FDG PET-CT")
        add(db, "2025-12-27", "biopsy", "FNAC of neck node")
        add(db, "2026-02-13", "chemotherapy", "Neoadjuvant chemotherapy")
        add(db, "2026-11-02", "imaging", "PET-CT")
        db.commit()
    j = client.get("/api/case/detail").json()["journey"]
    assert [(p["id"], p["title"]) for p in j["phases"]] == [
        ("workup", "Diagnosis & work-up"), ("treatment-1", "Treatment 1"), ("followup-1", "Follow-up & re-evaluation"),
        ("treatment-2", "Treatment 2"), ("followup-2", "Follow-up & surveillance"),
    ]
    by = {p["id"]: [i["title"] for i in p["items"]] for p in j["phases"]}
    assert by["followup-1"] == ["FDG PET-CT", "FNAC of neck node"]  # the recurrence work-up sits between the treatments
    assert by["treatment-2"] == ["Neoadjuvant chemotherapy"] and by["followup-2"] == ["PET-CT"]


@pytest.mark.parametrize("a,b,same", [
    (("2024-12-23", "biopsy", "Tongue lesion biopsy"), ("2024-12-23", "biopsy", "Biopsy procedure"), True),
    (("2024-12-23", "biopsy", "Biopsy collection"), ("2024-12-23", "biopsy", "Tongue lesion biopsy"), True),
    (("2025-12-26", "biopsy", "USG guided FNAC"), ("2025-12-27", "biopsy", "USG guided FNAC of node"), True),  # report date vs procedure date
    (("2025-01-11", "diagnosis", "Histopathology report"), ("2025-01-11", "diagnosis", "Histopathology diagnosis and staging"), True),
    (("2025-12-25", "imaging", "Plain MDCT Scan of Thorax"), ("2025-12-25", "imaging", "MDCT Scan of Neck with PNS"), False),  # two different scans
    (("2024-12-23", "biopsy", "Biopsy"), ("2025-06-01", "biopsy", "Biopsy"), False),
    (("2024-12-23", "biopsy", "Biopsy"), ("", "biopsy", "Biopsy"), False),  # undated is never merged into dated
    (("2024-12-23", "surgery", "Biopsy"), ("2024-12-23", "biopsy", "Biopsy"), False),
])
def test_same_event_rules(a, b, same):
    assert casefile.same_event(*a[:1], a[1], a[2], b[0], b[1], b[2]) is same


def test_same_day_lab_tests_collapse_into_one_item(journey):
    workup = next(p for p in journey["phases"] if p["id"] == "workup")
    group = next(i for i in workup["items"] if i["kind"] == "group")
    assert group["title"] == "3 lab tests" and "Blood Group" in group["detail"] and len(group["events"]) == 3
    assert len(workup["items"]) == 3  # consultation, biopsy, one lab group
    assert workup["count"] == 5


def test_undated_events_are_kept_apart(journey):
    assert [i["title"] for i in journey["undated"]] == ["Advised review"]
    assert all(i["date"] for p in journey["phases"] for i in p["items"])


def test_milestones_give_the_spine_of_the_story(journey):
    assert [m["title"] for m in journey["milestones"]] == [
        "Tongue lesion biopsy", "Wide excision and neck dissection", "Histopathology report", "Adjuvant radiotherapy advised",
        "Latest imaging: FDG PET-CT follow-up",
    ]
    assert journey["overview"].startswith("2024-12-23 Tongue lesion biopsy → 2025-01-09 Wide excision")


def test_without_treatment_everything_is_workup(client):
    with SessionLocal() as db:
        add(db, "2024-12-23", "biopsy", "Biopsy")
        add(db, "2025-06-01", "imaging", "CT scan")
        db.commit()
    j = client.get("/api/case/detail").json()["journey"]
    assert [p["id"] for p in j["phases"]] == ["workup"]


def test_near_duplicates_are_not_added_and_tidy_cleans_old_data(client):
    with SessionLocal() as db:
        assert add(db, "2025-01-09", "surgery", "Wide excision of left tongue and neck dissection")
        assert add(db, "2025-01-09", "surgery", "Wide excision and neck dissection of left tongue") is None
        # rows created before the rules existed: mis-categorised, duplicated, one entered by the user
        db.add_all([
            ClinicalEvent(event_date="2024-12-24", category="lab", title="Histopathology diagnosis"),
            ClinicalEvent(event_date="2024-12-24", category="diagnosis", title="Histopathology diagnosis result"),
            ClinicalEvent(event_date="2024-12-24", category="diagnosis", title="Histopathology diagnosis result", source="you"),
        ])
        db.commit()
        result = casefile.tidy_events(db)
        titles = [(e.category, e.source) for e in db.query(ClinicalEvent).filter_by(event_date="2024-12-24")]
    assert result["recategorised"] >= 1 and result["removed"] >= 1
    assert ("lab", "document") not in titles and ("diagnosis", "you") in titles  # the user's own entry survives
    assert casefile.tidy_events(SessionLocal()) == {"recategorised": 0, "removed": 0}  # idempotent


def test_you_can_date_an_undated_event_and_fix_its_type(client, journey):
    undated = client.get("/api/case/detail").json()["journey"]["undated"][0]
    assert client.patch(f"/api/case/events/{undated['id']}", json={"date": "not-a-date"}).status_code == 422
    r = client.patch(f"/api/case/events/{undated['id']}", json={"date": "2025-02-10", "category": "consultation", "title": "Oncology review"})
    assert r.status_code == 200
    j = r.json()["journey"]
    assert j["undated"] == []
    treatment = next(p for p in j["phases"] if p["id"] == "treatment-1")
    assert "Oncology review" in [i["title"] for i in treatment["items"]] or any(i["title"] == "Oncology review" for p in j["phases"] for i in p["items"])
    assert client.patch("/api/case/events/9999", json={"title": "x"}).status_code == 404


def test_journey_text_is_ordered_and_compact(client, journey):
    with SessionLocal() as db:
        text = casefile.journey_text(db)
    assert text.index("Diagnosis & work-up") < text.index("Treatment — surgery, radiotherapy (") < text.index("Follow-up & surveillance")
    assert "- 2024-12-25 [lab] 3 lab tests: Complete Blood Count, Blood Group, Biochemistry Report" in text
    assert "Date unknown" in text and "Overview:" in text


def test_chat_sees_the_ordered_journey(client, journey, monkeypatch):
    from app.services import llm

    seen = {}
    monkeypatch.setattr(llm, "chat", lambda s, i, **_: seen.setdefault("i", i) or "ok")
    client.post("/api/chat", json={"message": "Summarise the journey"})
    assert "Follow-up & surveillance" in seen["i"] and "3 lab tests" in seen["i"]


def test_rebuild_journey_adds_only_verified_events_in_the_background(client, monkeypatch):
    from app.services import llm

    client.post("/api/documents", files={"file": ("pet.txt", REPORT.encode(), "text/plain")})
    monkeypatch.setattr(llm, "chat_json", lambda s, i, **_: {"events": [
        {"date": "2026-11-02", "category": "imaging", "title": "FDG PET-CT", "detail": "Partial response", "quote": "18 F-FDG WHOLE BODY PET-CT STUDY"},
        {"date": "2026-07-22", "category": "imaging", "title": "MRI", "quote": "As compared to previous MRI dated 22-07-2026"},
        {"date": "2025-01-09", "category": "surgery", "title": "Invented surgery", "quote": "Patient underwent a wide local excision of the tongue"},
    ]})
    r = client.post("/api/case/rebuild-journey").json()
    assert r["queued"] == 1 and client.get("/api/case/detail").json()["journey"]["total"] == 0  # nothing happens in the request
    with SessionLocal() as db:
        jobs.run_pending(db)
    titles = [it["title"] for p in client.get("/api/case/detail").json()["journey"]["phases"] for it in p["items"]]
    assert titles == ["MRI", "FDG PET-CT"]  # ordered by date; the unverifiable event was dropped
    j = next(j for j in client.get("/api/jobs").json() if j["kind"] == "journey")
    assert j["status"] == "done" and j["added"] == 2
    # running it again re-reads but never duplicates
    assert client.post("/api/case/rebuild-journey").json()["queued"] == 1
    with SessionLocal() as db:
        jobs.run_pending(db)
    assert client.get("/api/case/detail").json()["journey"]["total"] == 2


def test_documents_without_any_analysis_get_queued(client):
    client.post("/api/documents", files={"file": ("pet.txt", REPORT.encode(), "text/plain")})  # legacy single upload: no job
    with SessionLocal() as db:
        assert jobs.enqueue_unanalyzed(db) == 1 and jobs.enqueue_unanalyzed(db) == 0
