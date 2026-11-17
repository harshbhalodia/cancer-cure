from app.database import SessionLocal
from app.models import Recommendation


def test_follow_up_requires_resolution_and_preserves_history(client):
    action = client.post("/api/actions", json={"title": "Ask the team a question", "owner": "Caregiver", "due_date": "2020-01-01"}).json()
    assert action["overdue"]
    assert client.patch(f"/api/actions/{action['id']}", json={"status": "resolved"}).status_code == 422
    contacted = client.patch(f"/api/actions/{action['id']}", json={"status": "contacted"}).json()
    assert len(contacted["history"]) == 2
    closed = client.patch(f"/api/actions/{action['id']}", json={"status": "resolved", "answer": "The team reviewed the question.", "answer_source": "clinician"}).json()
    assert not closed["overdue"] and len(closed["history"]) == 3
    assert client.get("/api/actions").json()["focus"] == []
    text = client.get("/api/actions/visit-summary").json()["text"]
    assert "The team reviewed" in text and "unverified" in text and "not a cancer response measurement" in text


def test_suggestions_keep_source_and_cannot_be_adopted_twice(client):
    with SessionLocal() as db:
        db.add(Recommendation(text="Ask whether repeat imaging is needed", quote="repeat imaging if clinically indicated", source="document"))
        db.commit()
    suggestion = client.get("/api/actions").json()["suggestions"][0]
    action = client.post("/api/actions", json={"source_key": suggestion["source_key"], "title": "Ignore this invented title"}).json()
    assert action["title"] == suggestion["title"] and action["evidence"]["quote"]
    assert client.post("/api/actions", json={"source_key": suggestion["source_key"]}).status_code == 409
    assert client.get("/api/actions").json()["suggestions"] == []


def test_actions_are_patient_local_and_reject_invalid_dates(client):
    patient = client.post("/api/workspaces", json={"label": "Synthetic B"}).json()
    headers = {"X-CC-Workspace": patient["id"]}
    action = client.post("/api/actions", json={"title": "Only patient A"}).json()
    assert client.get("/api/actions", headers=headers).json()["items"] == []
    assert client.patch(f"/api/actions/{action['id']}", headers=headers, json={"status": "dismissed"}).status_code == 404
    assert client.post("/api/actions", json={"title": "Bad date", "due_date": "2026-02-30"}).status_code == 422
    assert client.patch(f"/api/actions/{action['id']}", json={"owner": None}).status_code == 422
