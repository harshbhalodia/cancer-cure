import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest

from app.database import SessionLocal
from app.models import Job
from app.research_models import ResearchSource
from app.services import jobs, research_notebook

QUESTION = "What does the selected memo report about the project requirements?"
NEXT = "What does the selected appendix say about source version history?"
TEXT = (
    "This synthetic project accepts archived records for desk research. "
    "The synthetic review might miss unreported details. "
    "A separate appendix describes source version history."
)


def start(client):
    source = client.post("/api/research/notebook/sources", json={
        "title": "Synthetic research memo", "kind": "personal_note", "text": TEXT,
        "as_of": date.today().isoformat(),
    }).json()
    response = client.post("/api/research/notebook/loops", json={"question": QUESTION, "source_ids": [source["id"]]})
    assert response.status_code == 202
    return response.json(), source


def drain():
    with SessionLocal() as db:
        jobs.run_pending(db)


def latest(client):
    return client.get("/api/research/notebook").json()["loops"][0]


def approve(client, loop):
    return client.post(f"/api/research/notebook/loops/{loop['id']}/approve", json={
        "previous_job_id": loop["cycles"][-1]["job_id"],
    })


def model(monkeypatch, mode="", new_passages=False):
    sent = []
    generation = 0

    def respond(system, facts):
        nonlocal generation
        data = json.loads(facts.split("\n\n")[0])
        sent.append(data)
        if "selected_sources" in data:
            generation += 1
            source_id = data["selected_sources"][0]["id"]
            return {
                "reported_requirements": [{
                    "source_id": source_id, "passage_id": 1,
                    "interpretation": "The memo reports that archived records are accepted for this synthetic project.",
                }],
                "reported_concerns": [{
                    "source_id": source_id, "passage_id": 2,
                    "interpretation": "The review may miss details, so completeness remains unconfirmed.",
                }],
                "evidence_notes": [{
                    "source_id": source_id, "passage_id": 3,
                    "interpretation": "The memo reports a separate source-history appendix.",
                }] if new_passages and generation >= 2 else [],
                "unanswered_questions": ["Does the appendix include additional source details?"],
                "desk_research_tasks": ["Read the selected memo alongside the appendix."],
            }
        source_id = data["sources"][0]["id"]
        next_question = NEXT if generation == 1 else "What does the memo say about unreported review details?"
        if mode == "repeat":
            next_question = QUESTION.upper() + "!"
        raw = {
            "checks": [{
                "point_id": point["point_id"], "verdict": "supported",
                "reason": "The interpretation stays within the selected source wording.",
            } for point in data["points"]],
            "gaps": [{
                "question": next_question, "source_ids": [source_id],
                "answerability": "needs_new_source" if mode == "needs_source" else "within_selected_sources",
            }],
            "next_question": "" if mode == "no_question" else next_question,
        }
        if mode == "flagged":
            raw["checks"][0]["verdict"] = "overstated"
        elif mode == "unknown_check":
            raw["checks"][0]["point_id"] = "imaginary"
        elif mode == "missing_check":
            raw["checks"].pop()
        elif mode == "unknown_source":
            raw["gaps"][0]["source_ids"] = [99999]
        elif mode == "procedural":
            raw["checks"][0]["reason"] = "Manufacture your own vaccine."
        elif mode == "invented_figure":
            raw["checks"][0]["reason"] = "The source reports 99999 successful results."
        elif mode == "unlisted_next":
            raw["next_question"] = "What does an unlisted source establish about this project?"
        return raw

    monkeypatch.setattr(research_notebook.llm, "chat_json", respond)
    return sent


def test_cycles_freeze_only_selected_sources_and_wait_for_each_approval(client, monkeypatch):
    sent = model(monkeypatch, new_passages=True)
    loop, source = start(client)
    client.put("/api/case", json={"diagnosis": "UNRELATED_SYNTHETIC_CASE_DETAIL"})
    with SessionLocal() as db:
        db.get(ResearchSource, source["id"]).text = "Changed synthetic source after queueing."
        db.commit()
    drain()
    first = latest(client)
    assert first["status"] == "awaiting_approval"
    assert len(first["cycles"]) == 1
    assert first["sources"][0]["text"] == TEXT
    assert first["cycles"][0]["result"]["progress"]["additional_cited_passages"] == 2
    assert all("UNRELATED_SYNTHETIC_CASE_DETAIL" not in json.dumps(item) for item in sent)
    assert all("Changed synthetic source" not in json.dumps(item) for item in sent)
    assert len(sent) == 2
    assert approve(client, first).status_code == 202
    assert approve(client, first).status_code == 409
    drain()
    second = latest(client)
    assert len(second["cycles"]) == 2 and second["status"] == "awaiting_approval"
    assert second["cycles"][1]["question"] == NEXT
    assert second["cycles"][1]["result"]["progress"]["additional_cited_passages"] == 1
    assert approve(client, second).status_code == 202
    drain()
    third = latest(client)
    assert len(third["cycles"]) == 3 and third["status"] == "stopped"
    assert third["cycles"][-1]["result"]["stop_code"] == "cycle_limit"
    assert approve(client, third).status_code == 409
    with SessionLocal() as db:
        assert db.query(Job).filter_by(kind="vaccine").count() == 0
        assert db.query(ResearchSource).count() == 1


@pytest.mark.parametrize("mode,stop", [
    ("needs_source", "needs_new_sources"), ("repeat", "repeated_question"),
    ("flagged", "critique_requires_review"), ("no_question", "no_next_question"),
])
def test_loop_stops_instead_of_reinforcing_missing_or_questionable_evidence(client, monkeypatch, mode, stop):
    model(monkeypatch, mode)
    start(client)
    drain()
    loop = latest(client)
    assert loop["status"] == "stopped" and len(loop["cycles"]) == 1
    assert loop["cycles"][0]["result"]["stop_code"] == stop and loop["stop_reason"]
    assert approve(client, loop).status_code == 409


def test_unchanged_citations_stop_a_second_cycle_without_claiming_research_progress(client, monkeypatch):
    model(monkeypatch)
    start(client)
    drain()
    assert approve(client, latest(client)).status_code == 202
    drain()
    loop = latest(client)
    assert loop["status"] == "stopped"
    assert loop["cycles"][-1]["result"]["stop_code"] == "no_new_passages"
    assert loop["cycles"][-1]["result"]["progress"]["additional_cited_passages"] == 0


@pytest.mark.parametrize("mode", [
    "unknown_check", "missing_check", "unknown_source", "procedural", "invented_figure", "unlisted_next",
])
def test_unvalidated_critique_never_completes_a_cycle_or_enables_approval(client, monkeypatch, mode):
    sent = model(monkeypatch, mode)
    start(client)
    drain()
    loop = latest(client)
    assert loop["status"] == "failed"
    cycle = loop["cycles"][0]
    assert "critique rejected" in cycle["error"]
    assert "critique" not in cycle["result"]
    assert len(sent) == 3  # brief, critique, one bounded critique repair
    assert approve(client, loop).status_code == 409


def test_loops_are_isolated_duplicates_rejected_and_closing_prevents_model_work(client, monkeypatch):
    sent = model(monkeypatch)
    loop, source = start(client)
    body = {"question": QUESTION, "source_ids": [source["id"]]}
    assert client.post("/api/research/notebook/loops", json=body).status_code == 409
    patient = client.post("/api/workspaces", json={"label": "Synthetic loop isolation"}).json()
    headers = {"X-CC-Workspace": patient["id"]}
    assert client.get("/api/research/notebook", headers=headers).json()["loops"] == []
    assert client.post("/api/research/notebook/loops", headers=headers, json=body).status_code == 404
    assert client.post(f"/api/research/notebook/loops/{loop['id']}/close", headers=headers).status_code == 404
    assert client.post(f"/api/research/notebook/loops/{loop['id']}/approve", headers=headers, json={
        "previous_job_id": loop["cycles"][0]["job_id"],
    }).status_code == 404
    assert client.post(f"/api/research/notebook/loops/{loop['id']}/close").status_code == 200
    drain()
    assert latest(client)["closed"] and not sent
    assert latest(client)["cycles"][0]["status"] == "skipped"
    with SessionLocal() as db:
        assert db.query(Job).filter_by(kind="research_cycle", status="failed").count() == 0
    assert approve(client, latest(client)).status_code == 409


def test_concurrent_approvals_authorise_only_one_next_cycle(client, monkeypatch):
    model(monkeypatch)
    start(client)
    drain()
    loop = latest(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: approve(client, loop).status_code, range(2)))
    assert sorted(statuses) == [202, 409]
    assert len(latest(client)["cycles"]) == 2


def test_failed_cycle_retry_preserves_original_question_and_sources(client, monkeypatch):
    model(monkeypatch, "unknown_check")
    start(client)
    drain()
    loop = latest(client)
    failed = loop["cycles"][0]
    model(monkeypatch)
    assert client.post(f"/api/jobs/{failed['job_id']}/retry").status_code == 200
    drain()
    retried = latest(client)
    assert retried["status"] == "awaiting_approval"
    assert len(retried["cycles"]) == 1 and retried["cycles"][0]["job_id"] == failed["job_id"]
    assert retried["sources"] == loop["sources"]

