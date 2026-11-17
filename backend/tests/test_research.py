from __future__ import annotations

from contextlib import nullcontext
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import SessionLocal, init_db
from app.models import VaccineRun
from app.research_models import ResearchExperiment, ResearchEvidence
from app.services import research, workspaces


def test_existing_experiment_schema_is_upgraded_without_losing_snapshots(tmp_path):
    legacy = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    try:
        with legacy.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE cc_research_experiment ("
                "id INTEGER PRIMARY KEY, source_run_id INTEGER, hypothesis TEXT, "
                "input_hash VARCHAR(64), result_hash VARCHAR(64), predictor VARCHAR(120), "
                "dataset VARCHAR(12), candidate_counts JSON, selected JSON, caveats JSON, "
                "params JSON, created_at DATETIME)"
            )
            conn.exec_driver_sql(
                "INSERT INTO cc_research_experiment VALUES "
                "(1, 7, 'Synthetic legacy snapshot', 'input', 'result', 'test-predictor', "
                "'synthetic', '{}', '[]', '[]', '{}', '2026-01-01 00:00:00')"
            )
        init_db(legacy)
        init_db(legacy)
        with Session(legacy) as db:
            snapshot = db.scalars(select(ResearchExperiment)).one()
            assert snapshot.hypothesis == "Synthetic legacy snapshot"
            assert snapshot.comparison_hash == snapshot.pipeline_version == ""
            assert research.compare_experiments(snapshot, snapshot)["controlled"] is False
    finally:
        legacy.dispose()


def _run(
    db,
    *,
    input_hash="input-a",
    dataset="patient",
    predictor="predictor-a",
    selected=None,
    inputs=None,
    params=None,
    pipeline_version="vax-0.1",
    refs=None,
):
    selected = selected if selected is not None else [
        {"id": "KRAS-G12D-CVVGADGVGK", "score": 82.5, "flags": ["expression value incomplete"]},
        {"id": "TP53-R175H-PEPTIDE", "score": 61.0, "flags": []},
    ]
    params = params if params is not None else {"n_select": 12}
    result = {
        "input_hash": input_hash,
        "result_hash": f"result-{input_hash}",
        "predictor": predictor,
        "dataset": dataset,
        "pipeline_version": pipeline_version,
        "inputs": inputs if inputs is not None else {
            "variants_all": [{"id": 1, "gene": "KRAS", "protein_change": "G12D"}],
            "alleles": ["HLA-A*02:01"],
        },
        "refs": refs if refs is not None else {},
        "params": params,
        "selected": selected,
        "candidates": selected + [{"id": "unselected", "score": 10.0}],
        "rejected": [{"reason": "not selected"}],
        "stages": [{"name": "selection", "in": 3, "out": len(selected)}],
        "warnings": ["Computational predictions have limitations."],
    }
    row = VaccineRun(
        dataset=dataset,
        status="done",
        params=params,
        input_hash=input_hash,
        result_hash=f"result-{input_hash}",
        predictor=predictor,
        result=result,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _insert_run(workspace_id=None, **kwargs):
    context = workspaces.activate(workspace_id) if workspace_id else nullcontext()
    with context:
        with SessionLocal() as db:
            return _run(db, **kwargs).id


def test_local_ai_hypotheses_use_bounded_options_and_never_queue_execution(client, monkeypatch):
    from app.models import Job
    from app.services import jobs

    run_id = _insert_run()
    monkeypatch.setattr(research.llm, "chat_json", lambda *args: {"scenarios": [{"id": "stricter_vaf", "hypothesis": "How does a stricter VAF filter change the computational shortlist?"}]})
    url = f"/api/research/runs/{run_id}/hypotheses"
    assert client.post(url).status_code == 202
    assert client.post(url).status_code == 409
    with SessionLocal() as db:
        jobs.run_pending(db)
        assert db.query(VaccineRun).count() == 1
        assert db.query(Job).filter_by(kind="vaccine").count() == 0
    job = client.get(url).json()["job"]
    assert job["status"] == "done"
    assert job["result"]["proposals"][0]["params"]["min_vaf"] == 0.15


@pytest.mark.parametrize("response", [
    {"scenarios": [{"id": "invented", "hypothesis": "Question"}]},
    {"scenarios": [{"id": "stricter_vaf", "hypothesis": "Expect 99999 targets."}]},
    {"scenarios": [{"id": "stricter_vaf", "hypothesis": "Question", "params": {"min_vaf": 0}}]},
])
def test_invalid_local_hypotheses_fail_explicitly(client, monkeypatch, response):
    from app.services import jobs

    run_id = _insert_run()
    monkeypatch.setattr(research.llm, "chat_json", lambda *args: response)
    url = f"/api/research/runs/{run_id}/hypotheses"
    client.post(url)
    with SessionLocal() as db:
        jobs.run_pending(db)
    job = client.get(url).json()["job"]
    assert job["status"] == "failed" and job["error"]
    assert "proposals" not in job["result"]


def test_snapshot_ai_review_is_grounded_persists_and_survives_source_deletion(client, monkeypatch):
    from app.services import jobs

    run_id = _insert_run()
    snapshot = client.post("/api/research/experiments", json={"source_run_id": run_id, "hypothesis": "Synthetic test note"}).json()
    with SessionLocal() as db:
        db.delete(db.get(VaccineRun, run_id))
        db.commit()
    captured = []
    monkeypatch.setattr(research.llm, "chat", lambda system, facts: captured.append(facts) or "Stored computational scores are not clinical outcomes.")
    url = f"/api/research/experiments/{snapshot['id']}/review"
    assert client.post(url).status_code == 202
    with SessionLocal() as db:
        jobs.run_pending(db)
    job = client.get(url).json()["job"]
    assert job["status"] == "done" and job["result"]["experiment_id"] == snapshot["id"]
    assert "82.5" in captured[0] and "Synthetic test note" not in captured[0]
    assert client.get("/api/research/experiments").json()["items"][0]["selected"] == snapshot["selected"]


def test_ai_jobs_are_workspace_isolated_and_missing_model_does_not_look_successful(client, monkeypatch):
    from app.services import jobs

    run_id = _insert_run()
    patient = client.post("/api/workspaces", json={"label": "Synthetic AI isolation"}).json()
    url = f"/api/research/runs/{run_id}/hypotheses"
    assert client.get(url, headers={"X-CC-Workspace": patient["id"]}).status_code == 404

    def offline(*args):
        raise research.llm.LLMError("Synthetic offline test")

    monkeypatch.setattr(research.llm, "chat_json", offline)
    client.post(url)
    with SessionLocal() as db:
        jobs.run_pending(db)
    job = client.get(url).json()["job"]
    assert job["status"] == "failed" and "offline" in job["error"]


def test_evidence_comparison_keeps_unknowns_and_labels_user_profile(client):
    default_profile = client.get("/api/research/profile").json()
    assert default_profile == {
        "disease": "",
        "setting": "unknown",
        "prior_pd1": "unknown",
        "reported_unverified": True,
    }
    client.put(
        "/api/research/profile",
        json={"disease": "squamous cell carcinoma of tongue", "setting": "postoperative", "prior_pd1": "no"},
    )
    response = client.post(
        "/api/research/evidence",
        json={
            "source_url": "https://example.org/study",
            "study_id": "NCT01234567",
            "platform": "investigational platform",
            "disease": "tongue squamous carcinoma",
            "setting": "postoperative",
            "prior_pd1": "unknown",
            "endpoint_result": "Reported endpoint summary entered by user.",
            "n": 24,
            "followup": "12 months",
            "evidence_level": "peer_reviewed",
            "limitations": "Small, non-randomized study.",
            "as_of": date.today().isoformat(),
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user_entered_unverified"] is True
    assert data["comparison"]["resembles"] == ["disease", "setting"]
    assert data["comparison"]["unknown"] == ["sarcomatoid_differentiation", "prior_pd1"]
    assert data["comparison"]["dimensions"][0]["comparison_source"] == "user_reported_unverified_profile"
    assert client.get("/api/research/evidence").json()["items"][0]["id"] == data["id"]
    assert client.delete(f"/api/research/evidence/{data['id']}").status_code == 204
    assert client.get("/api/research/evidence").json()["items"] == []


def test_evidence_validation_rejects_non_http_links_future_dates_and_invalid_n(client):
    body = {
        "source_url": "file://local/study",
        "platform": "platform",
        "disease": "disease",
        "endpoint_result": "reported result",
        "evidence_level": "registry",
        "as_of": (date.today() + timedelta(days=1)).isoformat(),
        "n": 0,
    }
    assert client.post("/api/research/evidence", json=body).status_code == 422
    body["source_url"] = "https://example.org/study"
    assert client.post("/api/research/evidence", json=body).status_code == 422
    body["as_of"] = date.today().isoformat()
    assert client.post("/api/research/evidence", json=body).status_code == 422


@pytest.mark.parametrize(("disease", "expected"), [
    ("Tongue SCC", "unknown"),
    ("Tongue SCC with sarcomatoid differentiation", "resembles"),
    ("Tongue SCC without sarcomatoid differentiation", "differs"),
    ("Tongue SCC, suspected sarcomatoid differentiation", "unknown"),
    ("Tongue SCC; sarcomatoid differentiation not identified", "differs"),
])
def test_sarcomatoid_comparison_requires_explicit_non_tentative_wording(client, disease, expected):
    client.put("/api/research/profile", json={"disease": "Tongue SCC with sarcomatoid differentiation", "setting": "active_recurrent", "prior_pd1": "yes"})
    card = client.post("/api/research/evidence", json={
        "source_url": "https://example.org/synthetic", "platform": "Synthetic platform", "disease": disease,
        "endpoint_result": "Synthetic endpoint", "evidence_level": "registry", "as_of": date.today().isoformat()
    }).json()
    assert "sarcomatoid_differentiation" in card["comparison"][expected]


def test_profile_api_accepts_only_the_three_editable_profile_values(client):
    ui_profile = client.get("/api/research/profile").json()
    assert ui_profile["reported_unverified"] is True
    assert client.put("/api/research/profile", json=ui_profile).status_code == 422
    payload = {key: ui_profile[key] for key in ("disease", "setting", "prior_pd1")}
    saved = client.put("/api/research/profile", json=payload)
    assert saved.status_code == 200 and saved.json()["reported_unverified"] is True


def test_disease_similarity_requires_recognized_matching_site_and_histology(client):
    client.put(
        "/api/research/profile",
        json={"disease": "lung squamous cell carcinoma", "setting": "unknown", "prior_pd1": "unknown"},
    )
    base = {
        "source_url": "https://example.org/study",
        "platform": "platform",
        "setting": "unknown",
        "prior_pd1": "unknown",
        "endpoint_result": "User-entered endpoint note.",
        "evidence_level": "registry",
        "as_of": date.today().isoformat(),
    }
    tongue = client.post("/api/research/evidence", json={**base, "disease": "tongue squamous cell carcinoma"}).json()
    generic = client.post("/api/research/evidence", json={**base, "disease": "squamous cell carcinoma"}).json()
    assert tongue["comparison"]["differs"] == ["disease"]
    assert generic["comparison"]["dimensions"][0]["status"] == "unknown"


def test_experiment_comparison_uses_underlying_pipeline_inputs_not_input_hash(client):
    shared_inputs = {
        "variants_all": [{"id": 1, "gene": "KRAS", "protein_change": "G12D"}],
        "alleles": ["HLA-A*02:01"],
    }
    with SessionLocal() as db:
        first = _run(db, input_hash="hash-includes-params-A", inputs=shared_inputs, params={"n_select": 5})
        first_id = first.id
        second = _run(db, input_hash="hash-includes-params-B", inputs=shared_inputs, params={"n_select": 8})
        second_id = second.id
    first_snapshot = client.post("/api/research/experiments", json={"source_run_id": first_id, "hypothesis": "A"}).json()
    second_snapshot = client.post("/api/research/experiments", json={"source_run_id": second_id, "hypothesis": "B"}).json()
    comparison = client.get(
        f"/api/research/experiments/compare?left_id={first_snapshot['id']}&right_id={second_snapshot['id']}"
    ).json()
    assert first_snapshot["input_hash"] != second_snapshot["input_hash"]
    assert first_snapshot["comparison_hash"] == second_snapshot["comparison_hash"]
    assert comparison["controlled"] is True
    assert comparison["changed_params"] == [{
        "name": "n_select", "left": 5, "right": 8, "left_present": True, "right_present": True,
    }]


def test_missing_pipeline_inputs_never_count_as_controlled(client):
    with SessionLocal() as db:
        first_id = _run(db, input_hash="same-fake-hash", inputs={}).id
        second_id = _run(db, input_hash="same-fake-hash", inputs={}).id
    first = client.post("/api/research/experiments", json={"source_run_id": first_id, "hypothesis": "A"}).json()
    second = client.post("/api/research/experiments", json={"source_run_id": second_id, "hypothesis": "B"}).json()
    result = client.get(f"/api/research/experiments/compare?left_id={first['id']}&right_id={second['id']}").json()
    assert first["comparison_hash"] == second["comparison_hash"] == ""
    assert result["controlled"] is False
    assert result["warning"]


def test_research_evidence_profile_and_snapshots_are_workspace_isolated(client):
    patient = client.post("/api/workspaces", json={"label": "Research isolation test"}).json()
    headers = {"X-CC-Workspace": patient["id"]}
    first_run_id = _insert_run()
    second_run_id = _insert_run()
    workspace_run_id = _insert_run(patient["id"])

    evidence = {
        "source_url": "https://example.org/study",
        "platform": "platform",
        "disease": "test disease",
        "setting": "unknown",
        "prior_pd1": "unknown",
        "endpoint_result": "User-entered note.",
        "evidence_level": "registry",
        "as_of": date.today().isoformat(),
    }
    assert client.post("/api/research/evidence", json={**evidence, "study_id": "PRIMARY"}).status_code == 201
    assert client.post("/api/research/evidence", headers=headers, json={**evidence, "study_id": "WORKSPACE"}).status_code == 201
    client.put("/api/research/profile", json={"disease": "primary disease", "setting": "unknown", "prior_pd1": "unknown"})
    client.put(
        "/api/research/profile",
        headers=headers,
        json={"disease": "workspace disease", "setting": "unknown", "prior_pd1": "unknown"},
    )
    assert client.get("/api/research/profile").json()["disease"] == "primary disease"
    assert client.get("/api/research/profile", headers=headers).json()["disease"] == "workspace disease"
    assert client.get("/api/research/evidence").json()["items"][0]["study_id"] == "PRIMARY"
    assert client.get("/api/research/evidence", headers=headers).json()["items"][0]["study_id"] == "WORKSPACE"

    primary = client.post(
        "/api/research/experiments",
        json={"source_run_id": first_run_id, "hypothesis": "primary snapshot"},
    )
    assert primary.status_code == 201
    assert client.post(
        "/api/research/experiments",
        headers=headers,
        json={"source_run_id": second_run_id, "hypothesis": "must not access primary run"},
    ).status_code == 404
    workspace_snapshot = client.post(
        "/api/research/experiments",
        headers=headers,
        json={"source_run_id": workspace_run_id, "hypothesis": "workspace snapshot"},
    )
    assert workspace_snapshot.status_code == 201
    assert client.get("/api/research/experiments").json()["items"][0]["hypothesis"] == "primary snapshot"
    assert client.get("/api/research/experiments", headers=headers).json()["items"][0]["hypothesis"] == "workspace snapshot"


def test_experiment_snapshot_is_frozen_and_comparison_marks_non_equivalence(client):
    with SessionLocal() as db:
        first_run = _run(db)
        first_run_id = first_run.id
        second_run = _run(
            db,
            input_hash="input-a",
            inputs={
                "variants_all": [{"id": 1, "gene": "EGFR", "protein_change": "L858R"}],
                "alleles": ["HLA-A*02:01"],
            },
            selected=[
                {"id": "KRAS-G12D-CVVGADGVGK", "score": 79.0, "flags": ["different parameter set"]},
                {"id": "EGFR-L858R-PEPTIDE", "score": 55.0, "flags": []},
            ],
        )
        second_run_id = second_run.id

    snap_a = client.post("/api/research/experiments", json={"source_run_id": first_run_id, "hypothesis": "Compare parameter set A."})
    snap_b = client.post("/api/research/experiments", json={"source_run_id": second_run_id, "hypothesis": "Compare parameter set B."})
    assert snap_a.status_code == snap_b.status_code == 201
    a, b = snap_a.json(), snap_b.json()
    assert a["computational_only"] is True
    assert a["candidate_counts"]["candidate_count"] == 3

    comparison = client.get(f"/api/research/experiments/compare?left_id={a['id']}&right_id={b['id']}").json()
    assert comparison["controlled"] is False
    assert "Non-controlled comparison" in comparison["warning"]
    assert comparison["added_ids"] == ["EGFR-L858R-PEPTIDE"]
    assert comparison["removed_ids"] == ["TP53-R175H-PEPTIDE"]
    shared = comparison["shared_differences"][0]
    assert shared["score_delta"] == -3.5 and shared["rank_delta"] == 0

    with SessionLocal() as db:
        source = db.get(VaccineRun, first_run_id)
        source.result["selected"] = []
        db.delete(source)
        db.commit()
    frozen = client.get("/api/research/experiments").json()["items"]
    stored = next(item for item in frozen if item["id"] == a["id"])
    assert stored["selected"] == a["selected"]
    assert stored["params"] == {"n_select": 12}


def test_comparison_is_controlled_only_for_matching_input_dataset_and_predictor():
    left = ResearchExperiment(
        id=1, source_run_id=10, hypothesis="A", input_hash="same", result_hash="r1",
        comparison_hash="comparison", pipeline_version="v1", predictor="p", dataset="synthetic",
        candidate_counts={}, selected=[{"id": "x", "rank": 1, "score": 4.0, "caveats": []}],
        caveats=[], params={},
    )
    right = ResearchExperiment(
        id=2, source_run_id=11, hypothesis="B", input_hash="same", result_hash="r2",
        comparison_hash="comparison", pipeline_version="v1", predictor="p", dataset="synthetic",
        candidate_counts={}, selected=[{"id": "x", "rank": 2, "score": 3.0, "caveats": []}],
        caveats=[], params={},
    )
    report = research.compare_experiments(left, right)
    assert report["controlled"] is True and report["shared_differences"][0]["score_delta"] == -1.0
    assert report["changed_params"] == []
    right.dataset = "patient"
    assert research.compare_experiments(left, right)["controlled"] is False
