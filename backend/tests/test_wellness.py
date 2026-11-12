from datetime import date, timedelta

import pytest

from app.database import SessionLocal
from app.models import Document
from app.services import advisors, jobs, llm, wellness


def day(n: int = 0) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def test_habits_are_deduplicated_and_ticked_per_day(client):
    with SessionLocal() as db:
        a = wellness.add_habit(db, domain="diet", title="Protein at every meal")
        assert wellness.add_habit(db, domain="diet", title="protein at every meal!") is None
        assert wellness.add_habit(db, domain="nonsense", title="x") is None
        db.commit()
        for n in (0, 1, 2):
            wellness.set_done(db, a.id, day(n), True)
        wellness.set_done(db, a.id, day(0), True)  # ticking twice is harmless
        view = wellness.today_view(db)
        h = view["habits"][0]
        assert (view["done"], view["total"], h["streak"], h["week"][-3:]) == (1, 1, 3, [True, True, True])
        wellness.set_done(db, a.id, day(0), False)
        assert wellness.today_view(db)["habits"][0]["streak"] == 2  # yesterday still counts until today ends


def test_future_days_cannot_be_ticked_or_checked_in(client):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    with SessionLocal() as db:
        hid = wellness.add_habit(db, domain="mind", title="Breathing").id
        db.commit()
    assert client.put(f"/api/wellness/habits/{hid}/log", json={"day": tomorrow}).status_code == 422
    assert client.put("/api/wellness/checkin", json={"day": tomorrow, "energy": 3}).status_code == 422
    assert client.put("/api/wellness/checkin", json={"energy": 9}).status_code == 422


def test_checkin_updates_partially_and_blank_is_unknown_not_zero(client):
    r = client.put("/api/wellness/checkin", json={"energy": 4, "pain": 2, "intention": "Walk to the gate"}).json()
    assert r["alert"] is None
    r = client.put("/api/wellness/checkin", json={"mood": 3, "pain": None}).json()["checkin"]
    assert (r["energy"], r["mood"], r["pain"], r["intention"]) == (4, 3, None, "Walk to the gate")
    assert r["appetite"] is None and r["weight_kg"] is None


def test_checkin_raises_an_alert_for_red_flags_and_severe_pain(client):
    r = client.put("/api/wellness/checkin", json={"symptoms": "I cannot breathe properly"}).json()
    assert r["alert"] and r["alert"]["level"] == "emergency"
    r = client.put("/api/wellness/checkin", json={"symptoms": "", "pain": 9}).json()
    assert r["alert"] and "oncology team" in r["alert"]["message"]


def test_trends_compare_this_week_with_last_and_know_which_direction_is_better(client):
    with SessionLocal() as db:
        for n, (energy, pain) in {0: (4, 1), 1: (4, 2), 2: (4, 1), 8: (2, 4), 9: (2, 5), 10: (3, 4)}.items():
            wellness.save_checkin(db, day(n), {"energy": energy, "pain": pain})
        t = {m["key"]: m for m in wellness.trends(db)["metrics"]}
        assert t["energy"]["verdict"] == "better" and t["pain"]["verdict"] == "better"  # pain fell, which is better
        assert t["mood"]["verdict"] is None  # no data: no verdict, never a guess
        assert any("Pain averaged" in h["text"] for h in wellness.trends(db)["headlines"])


def test_adherence_counts_only_days_since_the_habit_was_added(client):
    with SessionLocal() as db:
        a = wellness.add_habit(db, domain="movement", title="Walk")
        db.commit()
        for n in (0, 1):
            wellness.set_done(db, a.id, day(n), True)
        adherence = wellness.trends(db)["adherence"][0]
        assert adherence["this_week"] == 1.0 and adherence["last_week"] is None


MED_DOC = "Discharge advice 13/12/24. Tab. Pantoprazole 40 mg once daily before breakfast for 2 weeks. Syp. Sucralfate 10 ml thrice daily."


def test_medicines_come_from_documents_as_quoted_suggestions(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *_a, **_k: {"medicines": [
        {"name": "Tab. Pantoprazole", "dose": "40 mg once daily before breakfast for 2 weeks", "purpose": "", "prescriber": "Dr Shah",
         "quote": "Tab. Pantoprazole 40 mg once daily before breakfast"},
        {"name": "Zolpidem", "dose": "10 mg", "quote": "Zolpidem 10 mg at night"},  # not in the document
    ]})
    with SessionLocal() as db:
        doc = Document(filename="advice.txt", sha256="abc123", stored_name="x", doc_type="advice", status="indexed", text_source="text_layer", doc_date="2024-12-13")
        db.add(doc)
        db.commit()
        monkeypatch.setattr("app.services.scan_extract.document_text", lambda _db, _d: MED_DOC)
        found, rejected = wellness.extract_medicines(db, doc)
        assert [m["name"] for m in found] == ["Tab. Pantoprazole"] and len(rejected) == 1
        assert wellness.add_found_medicines(db, doc, found) == 1
        assert wellness.add_found_medicines(db, doc, found) == 0
        db.commit()
        view = wellness.today_view(db)
        assert view["total"] == 0 and view["suggested_medicines"][0]["quote"].startswith("Tab. Pantoprazole")
        # the same medicine written differently is still one medicine
        assert wellness.add_habit(db, domain="medication", title="Pantoprazole 40") is None


def test_medicine_reading_skips_documents_that_cannot_list_medicines(client, monkeypatch):
    assert wellness.worth_reading(MED_DOC, "advice")
    assert not wellness.worth_reading("FDG PET-CT shows uptake 98 mg/dL", "imaging")
    assert not wellness.worth_reading("The report is normal.", "advice")


def test_wellbeing_pack_loads_and_may_use_general_figures_but_still_no_dose_orders():
    pack = advisors.load_packs()["carecompanion.wellbeing"]
    assert "wellbeing" in pack.inputs and pack.allow_figures
    text = "Sit for 5 minutes of slow breathing and walk 10 minutes."
    assert advisors.validate_output(text, "no numbers here", set(), pack.allow_figures)[1] == []
    assert any(v.startswith("invented-figure") for v in advisors.validate_output(text, "no numbers here", set())[1])
    assert "dosing-instruction" in advisors.validate_output("Take 20 mg tonight.", "", set(), True)[1]


def test_strategy_plan_goes_stale_when_the_daily_plan_changes_but_next_steps_does_not(client, monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *_a, **_k: "A short note. " + advisors.DEFAULT_DISCLAIMER)
    with SessionLocal() as db:
        for pid in ("carecompanion.wellbeing", "carecompanion.next_steps"):
            pack = advisors.load_packs()[pid]
            advisors.save_plan(db, pack, advisors.PackRun(markdown="x", notes=[], scopes=[], flags=[], used_fallback=False))
        assert not advisors.latest_plan(db, "carecompanion.wellbeing")["stale"]
        wellness.add_habit(db, domain="diet", title="Soups")
        db.commit()
        assert advisors.latest_plan(db, "carecompanion.wellbeing")["stale"]
        assert not advisors.latest_plan(db, "carecompanion.next_steps")["stale"]


def test_chat_context_includes_self_reported_daily_life(client):
    with SessionLocal() as db:
        wellness.add_habit(db, domain="medication", title="Pantoprazole", dose="40 mg once daily")
        wellness.save_checkin(db, day(0), {"energy": 2, "note": "tired after lunch"})
        text = wellness.context_lines(db)
    assert "Pantoprazole (40 mg once daily)" in text and "tired after lunch" in text


def test_medicine_jobs_run_in_the_background_after_recommendations(client, monkeypatch):
    from tests.test_jobs import bulk, drain

    def fake_json(system, *_a, **_k):
        if "medicines" in system.lower()[:200] or '"medicines"' in system:
            return {"medicines": [{"name": "Pantoprazole", "dose": "40 mg once daily", "quote": "Tab. Pantoprazole 40 mg once daily before breakfast"}]}
        return {"recommendations": [], "events": [], "findings": [], "fields": {}}

    monkeypatch.setattr(llm, "chat_json", fake_json)
    bulk(client, [("advice.txt", MED_DOC.encode())])
    drain()
    with SessionLocal() as db:
        assert [h["title"] for h in wellness.today_view(db)["suggested_medicines"]] == ["Pantoprazole"]
        assert jobs.enqueue_meds_rebuild(db) == 1  # a manual re-scan queues the document again


@pytest.mark.parametrize("path", ["/api/wellness/today", "/api/wellness/trends", "/api/wellness/library"])
def test_wellness_endpoints_answer_on_an_empty_record(client, path):
    r = client.get(path)
    assert r.status_code == 200
