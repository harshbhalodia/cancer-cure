import pytest

from app.services import llm
from app.services import documents as docs
from tests.conftest import SAMPLE_REPORT


def test_extract_message_ignores_reasoning():
    payload = {"output": [{"type": "reasoning", "content": "thinking..."}, {"type": "message", "content": "Hello!"}]}
    assert llm.extract_message(payload) == "Hello!"


def test_extract_message_reasoning_only_is_error():
    with pytest.raises(llm.LLMError):
        llm.extract_message({"output": [{"type": "reasoning", "content": "..."}]})


def test_guess_date_and_type():
    assert docs.guess_date(SAMPLE_REPORT) == "2026-11-02"
    assert docs.guess_type(SAMPLE_REPORT) == "imaging"
    assert docs.guess_type("Oncology OPD note. Patient reviewed with PET-CT. Advised review after 3 weeks; dietitian referral.") == "advice"
    assert docs.guess_type("Hemoglobin 12.1. Platelet 245. Creatinine 0.9 (reference range 0.7-1.3)") == "lab"
    assert docs.guess_type("hello") == "other"
    assert docs.guess_type("Impression: squamous cell carcinoma noted. Malignant cells.", "CT SCAN OF THORAX.pdf") == "imaging"
    assert docs.guess_type("", "JIVANBHAI_LAB_REPORT.pdf") == "lab"
    assert docs.guess_type("CYTOLOGY REPORT. FNAC smear shows malignant squamous cells. Impression: squamous cell carcinoma.") == "pathology"


def upload(client, name="pet.txt", body=SAMPLE_REPORT):
    return client.post("/api/documents", files={"file": (name, body.encode(), "text/plain")})


def test_upload_dedupes_and_indexes(client):
    first = upload(client).json()
    assert first["status"] == "indexed" and first["doc_type"] == "imaging" and first["doc_date"] == "2026-11-02"
    assert upload(client, "copy.txt").json()["already_uploaded"] is True
    assert len(client.get("/api/documents").json()) == 1
    kinds = [e["kind"] for e in client.get("/api/timeline").json()]
    assert kinds == ["document"]


def test_image_upload_flagged_for_ocr(client):
    r = client.post("/api/documents", files={"file": ("scan.png", b"\x89PNG fake", "image/png")}).json()
    assert r["status"] == "needs_ocr"


def test_delete_removes_search_rows(client):
    doc_id = upload(client).json()["id"]
    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    from app.database import SessionLocal
    from app.services import retrieval

    with SessionLocal() as db:
        assert retrieval.search(db, "tongue lesion") == []


def test_case_update_logs_event(client):
    body = {"diagnosis": "Carcinoma of tongue", "stage": ""}
    assert client.put("/api/case", json=body).json()["diagnosis"] == "Carcinoma of tongue"
    events = client.get("/api/timeline").json()
    assert events[0]["kind"] == "case" and "diagnosis" in events[0]["detail"]
    client.put("/api/case", json=body)  # no change → no new event
    assert len(client.get("/api/timeline").json()) == 1
