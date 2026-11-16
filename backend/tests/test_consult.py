from datetime import date

from app.database import SessionLocal
from app.models import ClinicalEvent, Recommendation
from app.services import consult, recommendations, wellness
from tests.test_record import _save


def _questions(db):
    return {s["id"]: s for s in consult.sections(db)}


def test_checklist_covers_the_scenario_in_priority_order(client, monkeypatch):
    _save(client, monkeypatch)
    with SessionLocal() as db:
        ss = consult.sections(db)
        assert [s["id"] for s in ss][:3] == ["vessel", "residual", "node"] and ss[-1]["id"] == "plan"
        assert ss[0]["priority"] == "urgent"
        vessel = " ".join(q["text"] for q in ss[0]["questions"])
        assert "Doppler" in vessel and "lungs" in vessel and "anticoagulant" in vessel
        assert "Right neck node: 8 mm → 4 mm" in " ".join(_questions(db)["node"]["context"])
        plan = " ".join(q["text"] for q in ss[-1]["questions"])
        assert "tumour board" in plan and "treatment objective" in plan and "MRI of 2026-07-22" in plan
        assert len(consult.leave_with(db)) == 3
        text = consult.checklist_text(db)
    assert "[ ]" in text and "seek emergency care" in text


def test_mention_list_uses_what_the_app_already_knows(client):
    with SessionLocal() as db:
        wellness.add_habit(db, domain="medication", title="Pantoprazole", dose="40 mg once daily")
        db.commit()
        wellness.save_checkin(db, "2026-11-01", {"weight_kg": 62, "symptoms": "neck feels tight"})
        wellness.save_checkin(db, "2026-11-10", {"weight_kg": 60.5, "pain": 3, "appetite": 2})
        notes = {m["id"]: m["note"] for m in consult.mention(db)}
    assert "62 kg on 2026-11-01 → 60.5 kg on 2026-11-10" in notes["weight"]
    assert "neck feels tight" in notes["neck"] and "Pantoprazole (40 mg once daily)" in notes["meds"]
    assert "3/10" in notes["tongue"] and "2.0/5" in notes["eating"]


def test_answers_are_saved_per_question_and_asked_follows_an_answer(client, monkeypatch):
    _save(client, monkeypatch)
    with SessionLocal() as db:
        key = consult.sections(db)[0]["questions"][1]["key"]
    assert client.put(f"/api/consult/items/{key}", json={"answer": "Doppler booked for Friday"}).status_code == 200
    v = client.get("/api/consult").json()
    assert v["answers"][key] == {"asked": True, "answer": "Doppler booked for Friday"}
    client.put(f"/api/consult/items/{key}", json={"asked": False})
    assert client.get("/api/consult").json()["answers"][key]["answer"] == "Doppler booked for Friday"


def test_finishing_the_visit_records_a_consultation_and_tracks_the_advice(client, monkeypatch):
    _save(client, monkeypatch)
    assert client.post("/api/consult/finish").status_code == 422  # nothing to record yet
    with SessionLocal() as db:
        key = consult.sections(db)[0]["questions"][0]["key"]
    client.put(f"/api/consult/items/{key}", json={"answer": "Seen today; scan arranged"})
    client.put("/api/consult/advice", json={"advice": "- Colour Doppler of the neck vein tomorrow\n- Review in 2 weeks with reports\n"})
    r = client.post("/api/consult/finish").json()
    assert r == {"saved": True, "recommendations": 2, "event": True}
    assert client.post("/api/consult/finish").json()["recommendations"] == 0  # saving again adds nothing twice
    with SessionLocal() as db:
        ev = db.query(ClinicalEvent).filter_by(source="you", category="consultation").one()
        assert ev.event_date == date.today().isoformat() and "Seen today; scan arranged" in ev.detail and "Colour Doppler" in ev.detail
        recs = {r.text: r for r in db.query(Recommendation).filter_by(source="you")}
        assert recs["Colour Doppler of the neck vein tomorrow"].category == "imaging"
        assert recs["Review in 2 weeks with reports"].category == "follow_up"
        assert recs["Review in 2 weeks with reports"].advisor.startswith("Doctor visit")
    assert client.get("/api/consult").json()["history"][0]["answered"] == 1


def test_no_scan_still_gives_a_usable_checklist(client):
    r = client.get("/api/consult").json()
    assert r["sections"] == [] and r["leave_with"] == [] and len(r["mention"]) == 5 and "emergency" in r["emergency"].lower()
