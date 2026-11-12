import os
import time
from pathlib import Path

from app.config import get_settings
from app.database import SessionLocal
from app.services import jobs, llm
from tests.conftest import SAMPLE_REPORT
from tests.test_record import GOOD, REPORT

CASE = {"patient_name": "Test Patient", "diagnosis": "carcinoma of tongue"}


def fake_json(system, _input, **_):
    return GOOD if "imaging report" in system else CASE


def bulk(client, files):
    return client.post("/api/documents/bulk", files=[("files", (n, b, "application/octet-stream")) for n, b in files])


def drain():
    with SessionLocal() as db:
        return jobs.run_pending(db)


def test_bulk_upload_returns_before_any_processing(client, monkeypatch):
    called = []
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: called.append(1) or CASE)
    r = bulk(client, [("pet.txt", REPORT.encode()), ("note.txt", b"Plain advice note 2026-10-01"), ("x.exe", b"MZ"), ("empty.txt", b"")]).json()
    assert r["queued"] == 2
    assert [x["status"] for x in r["results"]] == ["queued", "queued", "unsupported", "empty"]
    assert called == [] and client.get("/api/documents").json() == []  # nothing processed yet
    s = client.get("/api/jobs/summary").json()
    assert s["queued"] == 2 and s["pending_review"] == 0


def test_worker_ingests_then_analyzes_and_fills_inbox(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_json)
    bulk(client, [("pet.txt", REPORT.encode()), ("advice.txt", b"Doctor advice dated 03-11-2026: review in two weeks.")])
    assert drain() == 8  # 2 ingest + 2 analyze + 2 recommendation reads + 2 medicine reads
    docs = client.get("/api/documents").json()
    assert len(docs) == 2
    jobs_ = {j["filename"]: j for j in client.get("/api/jobs").json() if j["kind"] == "analyze"}
    assert jobs_["pet.txt"]["has_scan"] and jobs_["pet.txt"]["has_case"] and jobs_["pet.txt"]["review_status"] == "pending"
    assert jobs_["advice.txt"]["has_scan"] is False and jobs_["advice.txt"]["has_case"]
    s = client.get("/api/jobs/summary").json()
    assert s["pending_review"] == 2 and s["queued"] == 0 and s["failed"] == 0
    # Nothing is applied automatically
    assert client.get("/api/case").json()["diagnosis"] == ""
    assert client.get("/api/progress").json()["scans"] == []


def test_duplicates_skipped_and_ingest_order_first(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_json)
    bulk(client, [("a.txt", REPORT.encode())])
    drain()
    r = bulk(client, [("copy.txt", REPORT.encode())]).json()
    assert r["results"][0]["status"] == "duplicate" and r["queued"] == 0


def test_documents_searchable_before_analysis(client, monkeypatch):
    bulk(client, [("pet.txt", REPORT.encode())])
    with SessionLocal() as db:
        assert jobs.run_one(db)  # only the ingest job
    from app.services import retrieval

    with SessionLocal() as db:
        assert retrieval.search(db, "tongue lesion")
    assert client.get("/api/jobs/summary").json()["queued"] == 2  # analysis and recommendation reading still waiting


def test_failed_job_can_be_retried(client, monkeypatch):
    def down(*_a, **_k):
        raise llm.LLMError("Can't reach LM Studio.")

    monkeypatch.setattr(llm, "chat_json", down)
    bulk(client, [("pet.txt", REPORT.encode())])
    drain()
    failed = [j for j in client.get("/api/jobs").json() if j["status"] == "failed"]
    assert len(failed) == 2 and all("LM Studio" in f["error"] for f in failed)  # analysis and recommendation reading
    assert len(client.get("/api/documents").json()) == 1  # the document itself is safely stored
    monkeypatch.setattr(llm, "chat_json", fake_json)
    assert client.post("/api/jobs/retry-failed").json()["requeued"] == 2
    drain()
    assert client.get("/api/jobs/summary").json()["pending_review"] == 1


def test_resolve_parts_then_leaves_inbox(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_json)
    bulk(client, [("pet.txt", REPORT.encode())])
    drain()
    job = next(j for j in client.get("/api/jobs").json() if j["kind"] == "analyze")
    res = client.get(f"/api/jobs/{job['id']}/result").json()
    assert res["scan"]["lesions"] and res["case"]["fields"]["diagnosis"] == "carcinoma of tongue" and res["case"]["as_of"] == "2026-11-02"
    assert client.post(f"/api/jobs/{job['id']}/resolve", json={"part": "scan"}).json()["review_status"] == "pending"
    assert client.get(f"/api/jobs/{job['id']}/result").json()["scan"] is None
    assert client.post(f"/api/jobs/{job['id']}/resolve", json={"part": "case"}).json()["review_status"] == "reviewed"
    assert client.get("/api/jobs/summary").json()["pending_review"] == 0


def test_unreadable_image_fails_its_ocr_job_without_blocking_others(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_json)
    bulk(client, [("scan.png", b"\x89PNG fake"), ("ok.txt", REPORT.encode())])
    drain()
    jobs_ = client.get("/api/jobs").json()
    assert any(j["kind"] == "ocr" and j["status"] == "failed" for j in jobs_)
    assert any(j["kind"] == "analyze" and j["filename"] == "ok.txt" and j["status"] == "done" for j in jobs_)


def test_corrupt_pdf_fails_one_job_but_not_the_batch(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_json)
    bulk(client, [("bad.pdf", b"%PDF-1.4 not really a pdf"), ("ok.txt", SAMPLE_REPORT.encode())])
    drain()
    by = {j["filename"]: j for j in client.get("/api/jobs").json() if j["kind"] == "ingest"}
    assert by["bad.pdf"]["status"] == "failed" and by["ok.txt"]["status"] == "done"
    assert not list(get_settings().staging_dir.glob("*.pdf"))  # staged copy cleaned up


def test_inbox_folder_is_picked_up_once(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", fake_json)
    inbox = get_settings().inbox_dir
    inbox.mkdir(parents=True, exist_ok=True)
    f = inbox / "report.txt"
    f.write_text(REPORT)
    old = time.time() - 60
    os.utime(f, (old, old))
    (inbox / "ignore.exe").write_bytes(b"x")
    fresh = inbox / "still-copying.txt"
    fresh.write_text("x")  # just written: not settled yet
    assert jobs.scan_inbox() == 1
    assert jobs.scan_inbox() == 0
    drain()
    assert f.exists()  # the user's file is left in place
    jobs._seen.clear()
    assert jobs.scan_inbox() == 0  # already in the library, no new job


def test_interactive_gate_counts():
    assert jobs._interactive == 0
    with jobs.interactive():
        assert jobs._interactive == 1
    assert jobs._interactive == 0
