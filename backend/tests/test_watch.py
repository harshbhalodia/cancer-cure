from datetime import datetime, timedelta

import pytest

from app.database import SessionLocal
from app.models import Habit, Recommendation
from app.services import watch, wellness


def at(days_ago: int = 0, hour: int = 10) -> datetime:
    return (datetime.now().astimezone().replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=days_ago))


def keys(db, now):
    return {c["key"]: c for c in watch.candidates(db, now)}


def test_you_can_log_many_times_a_day_and_the_day_summary_follows(client):
    with SessionLocal() as db:
        for hour, e, p in ((8, 4, 2), (13, 3, 5), (20, 2, 3)):
            watch.log_reading(db, {"energy": e, "pain": p}, at(0, hour))
        assert [r["time"] for r in watch.readings_for(db, at().date().isoformat())] == ["08:00", "13:00", "20:00"]
        day = wellness.get_checkin(db, at().date().isoformat())
        assert (day["energy"], day["pain"]) == (3, 5)  # average energy, worst pain


def test_readings_are_validated_and_blank_means_not_measured(client):
    with SessionLocal() as db:
        with pytest.raises(ValueError):
            watch.log_reading(db, {})
        with pytest.raises(ValueError):
            watch.log_reading(db, {"pain": 11})
        r = watch.log_reading(db, {"temp_c": 101.3, "pulse": ""}, at(0, 9))  # entered in Fahrenheit
        assert r.temp_c == 38.5 and r.pulse is None


def test_emergency_symptom_gives_immediate_steps_and_clears_when_it_passes(client):
    with SessionLocal() as db:
        watch.log_reading(db, {"flags": ["breathless"]}, at(0, 10))
        snap = watch.snapshot(db, at(0, 10))
        top = snap["active"][0]
        assert top["level"] == "emergency" and snap["highest"] == "emergency"
        assert "112" in top["actions"][0]["text"] and top["actions"][0]["kind"] == "call"
        watch.sync(db, at(0, 20))  # more than 8 hours later with nothing new logged
        assert watch.active(db, at(0, 20)) == []
        assert watch.history(db)[0]["key"] == "flag:breathless"


def test_fever_alerts_then_is_recognised_as_recovering(client):
    with SessionLocal() as db:
        watch.log_reading(db, {"temp_c": 38.6}, at(0, 8))
        c = keys(db, at(0, 8))
        assert c["vitals:fever"]["level"] == "urgent" and c["vitals:fever"]["recheck"] == 30
        watch.log_reading(db, {"temp_c": 37.0}, at(0, 11))
        c = keys(db, at(0, 11))
        assert "vitals:fever" not in c and c["recover:fever"]["level"] == "recovering"


def test_low_oxygen_is_an_emergency_and_a_borderline_value_is_urgent(client):
    with SessionLocal() as db:
        watch.log_reading(db, {"spo2": 91}, at(0, 9))
        assert keys(db, at(0, 9))["vitals:spo2"]["level"] == "emergency"
        watch.log_reading(db, {"spo2": 93}, at(0, 10))
        assert keys(db, at(0, 10))["vitals:spo2"]["level"] == "urgent"


def test_neck_swelling_is_linked_to_the_reported_clot(client, monkeypatch):
    from tests.test_record import _save
    _save(client, monkeypatch)
    with SessionLocal() as db:
        watch.log_reading(db, {"flags": ["neck_swelling"]}, at(0, 9))
        c = keys(db, at(0, 9))["flag:neck_swelling"]
        assert c["level"] == "urgent" and "vein thrombosis" in c["actions"][0]["text"]


def test_worsening_against_your_own_baseline_is_caught_and_improvement_celebrated(client):
    with SessionLocal() as db:
        for d in range(9, 2, -1):
            watch.log_reading(db, {"pain": 2, "appetite": 2, "energy": 3}, at(d, 10))
        for d in (1, 0):
            watch.log_reading(db, {"pain": 5, "appetite": 4, "energy": 3}, at(d, 10))
        c = keys(db, at(0, 12))
        assert c["trend:pain_up"]["level"] == "urgent" and "5.0/10 vs your usual 2.0" in c["trend:pain_up"]["title"]
        assert c["recover:appetite"]["level"] == "recovering"
        assert "trend:energy_down" not in c  # unchanged measures stay quiet


def test_one_reading_is_not_a_trend_but_two_are(client):
    with SessionLocal() as db:
        for d in range(9, 2, -1):
            watch.log_reading(db, {"pain": 2}, at(d, 10))
        watch.log_reading(db, {"pain": 5}, at(0, 9))
        assert "trend:pain_up" not in keys(db, at(0, 10))
        watch.log_reading(db, {"pain": 5}, at(0, 12))
        assert keys(db, at(0, 13))["trend:pain_up"]["level"] == "urgent"


def test_a_steady_slide_is_predicted_before_it_crosses_the_line(client):
    with SessionLocal() as db:
        for i, v in enumerate([4, 4, 3, 3, 3, 2, 2]):
            watch.log_reading(db, {"appetite": v}, at(6 - i, 10))
        f = keys(db, at(0, 12)).get("forecast:appetite")
        assert f and f["level"] == "watch" and "within 3 days" in f["why"]


def test_big_weight_loss_is_flagged(client):
    with SessionLocal() as db:
        watch.log_reading(db, {"weight_kg": 64}, at(20, 9))
        watch.log_reading(db, {"weight_kg": 60.5}, at(0, 9))
        c = keys(db, at(0, 10))["trend:weight_loss"]
        assert c["level"] == "urgent" and "5.5%" in c["title"]


def test_medicines_missed_today_and_two_days_running(client):
    with SessionLocal() as db:
        h = wellness.add_habit(db, domain="medication", title="Pantoprazole", when="morning")
        db.commit()
        late = at(0, 23).replace(minute=50)
        assert keys(db, late)[f"med:today:{h.id}"]["level"] == "watch"
        assert "Do not double up" in keys(db, late)[f"med:today:{h.id}"]["actions"][1]["text"]
        wellness.set_done(db, h.id, at(0, 9).date().isoformat(), True)
        assert f"med:today:{h.id}" not in keys(db, late)
        wellness.set_done(db, h.id, at(0, 9).date().isoformat(), False)
        h.created_at = datetime.now().astimezone() - timedelta(days=5)
        db.commit()
        assert keys(db, late)[f"med:missed2:{h.id}"]["level"] == "urgent"


def test_words_of_despair_get_an_immediate_human_response(client):
    with SessionLocal() as db:
        watch.log_reading(db, {"note": "I feel hopeless today"}, at(0, 9))
        c = keys(db, at(0, 9))["mind:crisis"]
        assert c["level"] == "emergency" and "someone you trust" in c["actions"][0]["text"]


def test_an_urgent_report_item_left_open_becomes_an_alert(client):
    with SessionLocal() as db:
        r = Recommendation(text="Urgent assessment of the reported vein thrombosis", category="referral", source="app", urgency="urgent",
                           rec_date="2026-11-02", created_at=datetime.now().astimezone() - timedelta(days=2))
        db.add(r)
        db.commit()
        c = keys(db, at(0, 12))[f"report:{r.id}"]
        assert c["level"] == "urgent" and c["domain"] == "report"


def test_acknowledged_alerts_stay_quiet_until_they_get_worse(client):
    with SessionLocal() as db:
        watch.log_reading(db, {"temp_c": 38.2}, watch._now())
        s = watch.snapshot(db)["active"][0]
        watch.acknowledge(db, s["id"], "Called the team", recheck_minutes=60)
        assert watch.snapshot(db)["highest"] is None  # acknowledged, so not counted as open
        assert watch.active(db)[0]["status"] == "ack" and watch.active(db)[0]["ack_note"] == "Called the team"


def test_api_returns_the_next_steps_the_moment_something_is_logged(client):
    r = client.post("/api/watch/readings", json={"pain": 9, "note": "very sore"}).json()
    assert r["snapshot"]["highest"] == "urgent" and r["check_now"]
    assert client.get("/api/watch/summary").json()["headline"].startswith("Pain 9/10")
    assert client.post("/api/watch/readings", json={"pain": 99}).status_code == 422
    sid = r["snapshot"]["active"][0]["id"]
    assert client.post(f"/api/watch/signals/{sid}/ack", json={"note": "ok"}).status_code == 200
    rid = r["reading"]["id"]
    assert client.delete(f"/api/watch/readings/{rid}").status_code == 204
    assert client.get("/api/watch/signals").json()["highest"] is None  # the cause is gone, so the alert resolves


def test_advisors_and_chat_can_see_active_alerts(client):
    from app.services import advisors
    with SessionLocal() as db:
        watch.log_reading(db, {"flags": ["fever_chills"]}, watch._now())
        watch.snapshot(db)
        assert "Fever" in advisors.SCOPES["signals"](db)
        assert "signals" in advisors.load_packs()["carecompanion.wellbeing"].inputs
