from datetime import date, timedelta

from app.database import SessionLocal
from app.models import Recommendation
from app.services import casefile, nextsteps, priorities, recommendations, scan_extract, wellness
from tests.test_record import _save

VEIN_TEXT = (
    "Thrombosis of right internal jugular vein is seen with increased activity.\n It measures approx. 16 x 14 mm in axial plane (SUV Max.: 12).\n"
    " Length of the involvement is approx. 38 mm. Rest of the cervical soft tissues are normal."
)


def test_report_details_are_read_only_when_the_report_states_them(client, monkeypatch):
    with SessionLocal() as db:
        from app.models import Document, Scan
        doc = Document(filename="p.txt", sha256="x", stored_name="x", doc_type="imaging", status="indexed", text_source="text_layer")
        db.add(doc)
        db.flush()
        scan = Scan(document_id=doc.id, scan_date="2026-11-02")
        db.add(scan)
        db.commit()
        monkeypatch.setattr(scan_extract, "document_text", lambda _d, _x: VEIN_TEXT)
        assert priorities.report_details(db, scan) == {"size": "16 x 14 mm", "suv_max": "12", "length_mm": "38"}
        monkeypatch.setattr(scan_extract, "document_text", lambda _d, _x: "Thrombosis of right internal jugular vein is seen.")
        assert priorities.report_details(db, scan) == {}  # nothing is guessed


def test_latest_scan_becomes_three_tracks_and_tracked_items_once(client, monkeypatch):
    _save(client, monkeypatch)
    with SessionLocal() as db:
        ts = {t["id"]: t for t in priorities.tracks(db)}
        assert list(ts) == ["vessel", "residual", "strategy"]
        assert ts["vessel"]["priority"] == "urgent" and ts["residual"]["priority"] == "high"
        assert "34 mm → 18 mm" in ts["residual"]["facts"][0] and "10.8" in ts["residual"]["facts"][0]
        n = len([r for r in db.query(Recommendation).filter_by(source="app")])
        assert n == 5  # the save already synced; syncing again adds nothing
        assert priorities.sync(db) == 0 and db.query(Recommendation).filter_by(source="app").count() == n
        urgent = [r for r in db.query(Recommendation).filter_by(source="app", urgency="urgent")]
        assert len(urgent) == 3 and all(r.certainty == "suggested" for r in urgent)


def test_urgent_items_lead_the_do_next_list_and_the_vessel_card_is_not_duplicated(client, monkeypatch):
    _save(client, monkeypatch)
    with SessionLocal() as db:
        items = nextsteps.do_next(db, date(2026, 11, 11))
    assert [i["urgency"] for i in items[:3]] == ["urgent"] * 3 and items[0]["category"] == "referral"
    assert not any(i["id"].startswith("vascular-") for i in items)
    assert all("not a medical order" in i["detail"] for i in items[:5] if i.get("source") == "app")


def test_conditional_and_old_plans_are_demoted_and_labelled(client):
    with SessionLocal() as db:
        cond = recommendations.add(db, text="Brain MRI", category="imaging", advisor="Dr A", rec_date="2026-11-02", quote="MRI if there is a strong suspicion for brain metastases")
        old = recommendations.add(db, text="Plan for radical neck dissection", category="surgery", advisor="Dr B", rec_date="2026-02-13", certainty="planned")
        fresh = recommendations.add(db, text="Repeat blood tests next week", category="test", advisor="Dr C", rec_date=(date.today() - timedelta(days=5)).isoformat())
        db.commit()
        by = {r["id"]: r for r in recommendations.listing(db)}
        assert (by[cond.id]["nature"], by[old.id]["nature"], by[fresh.id]["nature"]) == ("conditional", "verify", "current")
        scores = {i["rec_id"]: i["score"] for i in nextsteps.do_next(db) if i["kind"] == "recommendation"}
        assert scores[fresh.id] > scores[old.id] > scores[cond.id]
        assert "OLD PLAN" in recommendations.context_lines(db) and "ONLY IF" in recommendations.context_lines(db)
        # confirming it was never carried out turns the old plan back into a pending item
        recommendations.set_status(db, old.id, "open", verified="not_done")
        assert {r["id"]: r for r in recommendations.listing(db)}[old.id]["nature"] == "current"
        assert "OLD PLAN" not in recommendations.context_lines(db)


def test_questions_ask_what_the_records_cannot_answer_and_apply_the_answers(client, monkeypatch):
    _save(client, monkeypatch)
    with SessionLocal() as db:
        old = recommendations.add(db, text="Radical neck dissection", category="surgery", advisor="Dr B", rec_date="2026-02-13", certainty="planned")
        db.commit()
        ids = [q["id"] for q in priorities.questions(db)]
        assert ids[:2] == ["treatment_status", "neck_symptoms"] and f"rec-{old.id}" in ids

        priorities.answer(db, "treatment_status", "on", "immunotherapy")
        assert "treatment_status" not in [q["id"] for q in priorities.questions(db)]
        values, _ = casefile.derive(db)
        assert "Still receiving treatment: immunotherapy" in values["current_treatment"]

        out = priorities.answer(db, "neck_symptoms", "yes")
        assert out["alert"] and "oncology team today" in out["alert"]["message"]
        from app.services import watch
        assert any(s["key"] == "flag:neck_swelling" and s["level"] == "urgent" for s in watch.active(db))
        assert "neck_symptoms" not in [q["id"] for q in priorities.questions(db)]

        priorities.answer(db, f"rec-{old.id}", "unsure")  # snoozed, not decided
        assert f"rec-{old.id}" not in [q["id"] for q in priorities.questions(db)]
        priorities.answer(db, f"rec-{old.id}", "done")
        assert {r["id"]: r for r in recommendations.listing(db)}[old.id]["status"] == "done"


def test_message_to_the_care_team_uses_only_recorded_figures(client, monkeypatch):
    _save(client, monkeypatch)
    r = client.get("/api/priorities").json()
    text = r["message"]["text"]
    assert r["message"]["available"] and "34 mm → 18 mm" in text and "SUVmax 10.8" in text
    assert "Doppler" in text and "next treatment plan" in text
    assert "cured" not in text.lower() and "will " not in text.lower().replace("will you", "")
    assert [t["id"] for t in r["tracks"]] == ["vessel", "residual", "strategy"]


def test_no_scan_means_no_priorities(client):
    r = client.get("/api/priorities").json()
    assert r["tracks"] == [] and not r["message"]["available"]
    assert priorities.questions is not None


def test_newer_scan_retires_older_suggestions(client, monkeypatch):
    _save(client, monkeypatch)
    with SessionLocal() as db:
        from app.models import Scan
        s = db.query(Scan).first()
        s.scan_date = "2026-01-01"
        db.commit()
        priorities.sync(db)
        s.scan_date = "2026-11-02"
        db.commit()
        # pretend the stored suggestions came from an older scan, then confirm they are replaced
        for r in db.query(Recommendation).filter_by(source="app"):
            r.rec_date = "2026-01-01"
        db.commit()
        priorities.sync(db)
        statuses = {r.rec_date: r.status for r in db.query(Recommendation).filter_by(source="app")}
        assert statuses["2026-01-01"] == "dismissed" and statuses["2026-11-02"] == "open"
