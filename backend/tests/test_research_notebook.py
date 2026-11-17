from copy import deepcopy
from datetime import date

import pytest

from app.config import get_settings, settings_context
from app.database import SessionLocal
from app.research_models import ResearchSource
from app.services import jobs, research_notebook


SOURCE_TEXT = (
    "This synthetic study requires surgery at the study centre. "
    "Prior treatment might reduce tissue suitability; this is a concern, not a confirmed finding. "
    "Archived paraffin tissue is not accepted in this study. "
    "The reply does not address histologic variants."
)
QUESTION = "Which requirements are study-specific and what questions remain unanswered?"


def source(client, text=SOURCE_TEXT):
    response = client.post("/api/research/notebook/sources", json={
        "title": "Synthetic study correspondence", "kind": "correspondence",
        "text": text, "as_of": date.today().isoformat(),
    })
    assert response.status_code == 201
    return response.json()


def answer(source_id):
    return {
        "reported_requirements": [{
            "source_id": source_id, "passage_id": 1,
            "interpretation": "The correspondence reports a study-specific site requirement, not a universal vaccine requirement.",
        }],
        "reported_concerns": [{
            "source_id": source_id,
            "passage_id": 2,
            "interpretation": "The author reports a concern; tissue suitability remains unconfirmed.",
        }],
        "evidence_notes": [],
        "unanswered_questions": ["Does the study include the histologic variant?"],
        "desk_research_tasks": ["Compare the reply with the study's published inclusion criteria."],
    }


def drain():
    with SessionLocal() as db:
        jobs.run_pending(db)


def test_notebook_snapshots_only_selected_sources_without_patient_or_pipeline_data(client, monkeypatch):
    chosen = source(client)
    source(client, "Unselected private synthetic note that must not enter this request.")
    client.put("/api/case", json={"diagnosis": "UNRELATED_SYNTHETIC_CASE_DETAIL"})
    sent = []

    def respond(system, facts):
        sent.append(facts)
        return answer(chosen["id"])

    monkeypatch.setattr(research_notebook.llm, "chat_json", respond)
    queued = client.post("/api/research/notebook/briefs", json={"question": QUESTION, "source_ids": [chosen["id"]]})
    assert queued.status_code == 202
    assert client.post("/api/research/notebook/briefs", json={"question": QUESTION, "source_ids": [chosen["id"]]}).status_code == 422
    with SessionLocal() as db:
        db.get(ResearchSource, chosen["id"]).text = "Synthetic correction added after the brief was queued."
        db.commit()
    drain()
    notebook = client.get("/api/research/notebook").json()
    brief = notebook["briefs"][0]
    assert brief["status"] == "done" and brief["result"]["reported_concerns"]
    assert brief["sources"][0]["text"] == SOURCE_TEXT
    assert brief["result"]["fingerprint"] == queued.json()["fingerprint"]
    assert "Unselected private" not in sent[0] and "UNRELATED_SYNTHETIC_CASE_DETAIL" not in sent[0]
    assert brief["result"]["reported_requirements"][0]["quote"] == SOURCE_TEXT.split(". ")[0] + "."
    assert brief["result"]["model"] == get_settings().lm_model


def test_passage_selection_copies_decimal_unicode_and_original_spacing_verbatim(client, monkeypatch):
    text = "Synthetic study \u2013 source excerpt.\nMore than 1.0 gram\u00a0of fresh tissue is required by this synthetic study."
    saved = source(client, text)
    raw = answer(saved["id"])
    raw["reported_requirements"][0]["passage_id"] = 2
    raw["reported_concerns"] = []
    monkeypatch.setattr(research_notebook.llm, "chat_json", lambda *args: raw)
    client.post("/api/research/notebook/briefs", json={"question": QUESTION, "source_ids": [saved["id"]]})
    drain()
    brief = client.get("/api/research/notebook").json()["briefs"][0]
    assert brief["status"] == "done"
    assert brief["result"]["reported_requirements"][0]["quote"] == text.split("\n")[1]
    assert brief["result"]["validation_repairs"] == 0


@pytest.mark.parametrize("defect", ["unknown_passage", "upgraded_concern"])
def test_failed_brief_retries_frozen_sources_and_repairs_invalid_draft_once(client, monkeypatch, defect):
    from app.models import Job

    saved = source(client)
    queued = client.post("/api/research/notebook/briefs", json={"question": QUESTION, "source_ids": [saved["id"]]}).json()
    with SessionLocal() as db:
        job = db.get(Job, queued["id"])
        job.status = "failed"
        job.error = "Local brief rejected: an attribution or exact source quotation could not be verified."
        db.get(ResearchSource, saved["id"]).text = "Changed synthetic source; it must not replace the frozen version."
        db.commit()
    calls = []

    def respond(system, facts):
        calls.append(facts)
        raw = answer(saved["id"])
        if len(calls) == 1:
            if defect == "unknown_passage":
                raw["reported_requirements"][0]["passage_id"] = 500
            else:
                raw["reported_requirements"].append(raw["reported_concerns"].pop())
        return raw

    monkeypatch.setattr(research_notebook.llm, "chat_json", respond)
    assert client.post(f"/api/jobs/{queued['id']}/retry").status_code == 200
    drain()
    brief = client.get("/api/research/notebook").json()["briefs"][0]
    assert brief["id"] == queued["id"] and brief["status"] == "done"
    assert brief["sources"][0]["text"] == SOURCE_TEXT and brief["question"] == QUESTION
    assert brief["result"]["validation_repairs"] == 1 and len(calls) == 2
    assert ("unknown source/passage" if defect == "unknown_passage" else "unconfirmed concern") in calls[1]
    assert "Changed synthetic source" not in calls[1]


@pytest.mark.parametrize("defect", [
    "unknown_source", "unknown_passage", "invented_quote", "upgraded_concern", "certain_concern",
    "invented_number", "procedural_task", "invalid_shape", "clipped_concern",
])
def test_notebook_rejects_ungrounded_or_procedural_model_output(client, monkeypatch, defect):
    saved = source(client)
    raw = deepcopy(answer(saved["id"]))
    if defect == "unknown_source":
        raw["reported_requirements"][0]["source_id"] += 50
    elif defect == "unknown_passage":
        raw["reported_requirements"][0]["passage_id"] = 99999
    elif defect == "invented_quote":
        raw["reported_requirements"][0]["quote"] = "An invented source quotation."
    elif defect == "upgraded_concern":
        raw["reported_requirements"].append(raw["reported_concerns"].pop())
    elif defect == "certain_concern":
        raw["reported_concerns"][0]["interpretation"] = "The tissue is necrotic and unsuitable."
    elif defect == "invented_number":
        raw["reported_requirements"][0]["interpretation"] = "The study reports 99999 successful outcomes."
    elif defect == "procedural_task":
        raw["desk_research_tasks"] = ["Manufacture your own vaccine."]
    elif defect == "clipped_concern":
        raw["evidence_notes"] = [{
            "source_id": saved["id"], "passage_id": 2,
            "interpretation": "Prior treatment reduced tissue suitability.",
        }]
    else:
        raw["unrecognised"] = "Unexpected output"
    monkeypatch.setattr(research_notebook.llm, "chat_json", lambda *args: raw)
    client.post("/api/research/notebook/briefs", json={"question": QUESTION, "source_ids": [saved["id"]]})
    drain()
    brief = client.get("/api/research/notebook").json()["briefs"][0]
    assert brief["status"] == "failed" and "rejected" in brief["error"]
    assert "reported_requirements" not in brief["result"]


def test_invalid_passages_still_fail_after_one_repair_and_do_not_create_findings(client, monkeypatch):
    saved = source(client)
    calls = []

    def bad_reference(*args):
        calls.append(True)
        raw = answer(saved["id"])
        raw["reported_requirements"][0]["source_id"] += 200
        return raw

    monkeypatch.setattr(research_notebook.llm, "chat_json", bad_reference)
    client.post("/api/research/notebook/briefs", json={"question": QUESTION, "source_ids": [saved["id"]]})
    drain()
    brief = client.get("/api/research/notebook").json()["briefs"][0]
    assert brief["status"] == "failed" and len(calls) == 2
    assert "validation-repair attempt" in brief["error"]
    assert "unknown source/passage" in brief["error"]
    assert "reported_requirements" not in brief["result"]


def test_notebook_is_patient_isolated_and_requires_valid_bounded_sources(client):
    saved = source(client)
    patient = client.post("/api/workspaces", json={"label": "Synthetic notebook isolation"}).json()
    headers = {"X-CC-Workspace": patient["id"]}
    assert client.get("/api/research/notebook", headers=headers).json()["sources"] == []
    assert client.get("/api/research/notebook", headers=headers).json()["briefs"] == []
    request = {"question": QUESTION, "source_ids": [saved["id"]]}
    assert client.post("/api/research/notebook/briefs", headers=headers, json=request).status_code == 404
    assert client.post("/api/research/notebook/briefs", json={**request, "source_ids": []}).status_code == 422
    assert client.post("/api/research/notebook/briefs", json={**request, "source_ids": [saved["id"], saved["id"]]}).status_code == 422
    large_ids = [source(client, "A" * 12000)["id"] for _ in range(4)]
    response = client.post("/api/research/notebook/briefs", json={**request, "source_ids": large_ids})
    assert response.status_code == 422 and "silently truncated" in response.json()["detail"]


@pytest.mark.parametrize("question", [
    "How to manufacture a TMV vaccine at home?",
    "Give me a protocol for isolating tumour vesicles.",
    "How do I store fresh tumour tissue for experiments?",
    "How to administer this vaccine?",
])
def test_notebook_does_not_queue_laboratory_or_treatment_protocols(client, question):
    saved = source(client)
    response = client.post("/api/research/notebook/briefs", json={"question": question, "source_ids": [saved["id"]]})
    assert response.status_code == 422
    assert client.get("/api/research/notebook").json()["briefs"] == []


def test_notebook_refuses_remote_model_and_surfaces_local_model_failure(client, monkeypatch):
    saved = source(client)
    body = {"question": QUESTION, "source_ids": [saved["id"]]}
    with settings_context(get_settings().model_copy(update={"lm_endpoint": "https://remote.example/api/v1/chat"})):
        with SessionLocal() as db:
            with pytest.raises(ValueError, match="loopback"):
                research_notebook.queue_brief(db, QUESTION, [saved["id"]])

    def offline(*args):
        raise research_notebook.llm.LLMError("Synthetic local-model offline test")

    monkeypatch.setattr(research_notebook.llm, "chat_json", offline)
    assert client.post("/api/research/notebook/briefs", json=body).status_code == 202
    drain()
    brief = client.get("/api/research/notebook").json()["briefs"][0]
    assert brief["status"] == "failed" and "offline" in brief["error"]


def test_notebook_requires_nonempty_appropriately_typed_sources(client):
    values = {"title": "Synthetic", "kind": "correspondence", "text": SOURCE_TEXT, "as_of": date.today().isoformat()}
    for changed in ({"text": " "}, {"as_of": "2999-01-01"}, {"kind": "confirmed_pathology"}, {"source_url": "file://secret"}):
        assert client.post("/api/research/notebook/sources", json={**values, **changed}).status_code == 422
