from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings
from app.database import SessionLocal
from app.models import Case
from app.services import jobs, workspaces


def test_patient_files_case_and_queue_are_isolated(client):
    patient = client.post("/api/workspaces", json={"label": "Synthetic patient B"}).json()
    headers = {"X-CC-Workspace": patient["id"]}
    client.put("/api/case", json={"diagnosis": "Synthetic diagnosis A"})
    assert client.get("/api/case", headers=headers).json()["diagnosis"] == ""
    client.put("/api/case", headers=headers, json={"diagnosis": "Synthetic diagnosis B"})
    assert client.get("/api/case").json()["diagnosis"] == "Synthetic diagnosis A"
    a = client.post("/api/documents", files={"file": ("report.txt", b"synthetic report A")}).json()
    assert client.get("/api/documents", headers=headers).json() == []
    assert client.get(f"/api/documents/{a['id']}/file", headers=headers).status_code == 404
    b = client.post("/api/documents", headers=headers, files={"file": ("report.txt", b"synthetic report B")}).json()
    assert client.get(f"/api/documents/{b['id']}/file", params={"workspace": patient["id"]}).content == b"synthetic report B"
    client.post("/api/documents/bulk", headers=headers, files={"files": ("queued.txt", b"synthetic queued B")})
    assert client.get("/api/jobs", headers=headers).json()
    assert not any(j["filename"] == "queued.txt" for j in client.get("/api/jobs").json())
    with workspaces.activate(patient["id"]):
        with SessionLocal() as db:
            jobs.run_one(db)
    assert any(d["filename"] == "queued.txt" for d in client.get("/api/documents", headers=headers).json())
    assert all(d["filename"] != "queued.txt" for d in client.get("/api/documents").json())


def test_unknown_workspace_never_falls_back_and_contexts_do_not_mix(client):
    patient = client.post("/api/workspaces", json={"label": "Synthetic B"}).json()
    assert client.get("/api/case?workspace=unknown").status_code == 404
    assert client.get("/api/case?workspace=primary", headers={"X-CC-Workspace": patient["id"]}).status_code == 400

    def read(workspace):
        with workspaces.activate(workspace):
            with SessionLocal() as db:
                case = db.get(Case, 1)
                return str(get_settings().data_dir), case.diagnosis

    client.put("/api/case", json={"diagnosis": "A"})
    client.put("/api/case", headers={"X-CC-Workspace": patient["id"]}, json={"diagnosis": "B"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(read, ["primary", patient["id"]]))
    assert a[0] != b[0] and (a[1], b[1]) == ("A", "B")


def test_workspace_labels_are_required_and_cohort_child_inherits_workspace(client):
    from app.services.cohort import _process_env

    assert client.post("/api/workspaces", json={"label": " "}).status_code == 422
    patient = client.post("/api/workspaces", json={"label": "Synthetic C"}).json()
    with workspaces.activate(patient["id"]):
        env = _process_env()
        assert env["CC_DATA_DIR"] == str(get_settings().data_dir)
        assert env["CC_INBOX_DIR"] == str(get_settings().inbox_dir)
        assert patient["id"] in env["CC_DATA_DIR"]
