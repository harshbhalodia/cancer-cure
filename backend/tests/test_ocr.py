import io

import pytest
from PIL import Image, ImageDraw

from app.database import SessionLocal
from app.models import Document, DocumentChunk
from app.services import documents, jobs, llm, ocr
from tests.test_jobs import CASE, GOOD, bulk, drain
from tests.test_record import REPORT


def page_image(blank: bool = False) -> Image.Image:
    img = Image.new("RGB", (600, 800), "white")
    if not blank:
        d = ImageDraw.Draw(img)
        for y in range(40, 760, 30):
            d.rectangle([40, y, 560, y + 14], fill="black")
    return img


def image_pdf(*pages: Image.Image) -> bytes:
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=list(pages[1:]))
    return buf.getvalue()


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def fake_json(system, _input, **_):
    return GOOD if "imaging report" in system else CASE


def test_scanned_pdf_is_read_indexed_and_then_analyzed(client, monkeypatch):
    pages_seen = []
    monkeypatch.setattr(llm, "vision", lambda prompt, b64, **_: pages_seen.append(1) or REPORT)
    monkeypatch.setattr(llm, "chat_json", fake_json)
    bulk(client, [("scan.pdf", image_pdf(page_image(), page_image()))])
    drain()
    doc = client.get("/api/documents").json()[0]
    assert len(pages_seen) == 2
    assert doc["status"] == "indexed" and doc["text_source"] == "vision_ocr" and doc["doc_type"] == "imaging" and doc["doc_date"] == "2026-11-02"
    # the analysis that originally had nothing to read is re-run on the transcribed text
    analyze = next(j for j in client.get("/api/jobs").json() if j["kind"] == "analyze")
    assert analyze["has_scan"] and analyze["review_status"] == "pending"
    with SessionLocal() as db:
        from app.services import retrieval

        hits = retrieval.search(db, "tongue lesion")
        assert hits and hits[0].ai_read is True


def test_photo_of_report_is_read(client, monkeypatch):
    monkeypatch.setattr(llm, "vision", lambda *a, **k: "Dr advice dated 13/12/24: biopsy advised")
    monkeypatch.setattr(llm, "chat_json", fake_json)
    bulk(client, [("PHOTO.jpeg", png_bytes(page_image()))])
    drain()
    doc = client.get("/api/documents").json()[0]
    assert doc["status"] == "indexed" and doc["doc_date"] == "2024-12-13"


def test_blank_pages_skip_the_model_and_unreadable_docs_are_not_analyzed(client, monkeypatch):
    monkeypatch.setattr(llm, "vision", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model must not be called for a blank page")))
    bulk(client, [("blank.png", png_bytes(page_image(blank=True)))])
    drain()
    doc = client.get("/api/documents").json()[0]
    assert doc["status"] == "unreadable"
    assert not [j for j in client.get("/api/jobs").json() if j["kind"] == "analyze" and j["status"] == "done" and j["review_status"] == "pending"]


def test_interrupted_reading_resumes_after_the_last_saved_page(client, monkeypatch):
    calls = []

    def flaky(prompt, b64, **_):
        calls.append(1)
        if len(calls) == 2:
            raise llm.LLMError("Can't reach LM Studio.")
        return f"Transcribed page {len(calls)} with enough characters to count as text."

    monkeypatch.setattr(llm, "vision", flaky)
    monkeypatch.setattr(llm, "chat_json", fake_json)
    bulk(client, [("two.pdf", image_pdf(page_image(), page_image()))])
    drain()
    failed = [j for j in client.get("/api/jobs").json() if j["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["kind"] == "ocr"
    with SessionLocal() as db:
        assert sorted({c.page for c in db.query(DocumentChunk)}) == [1]  # page 1 was kept
    assert client.post("/api/jobs/retry-failed").json()["requeued"] == 1
    drain()
    assert len(calls) == 3  # only page 2 was read again
    assert client.get("/api/documents").json()[0]["status"] == "indexed"


def test_legacy_scanned_docs_are_queued_and_reanalyzed(client, monkeypatch):
    """A document stored before OCR existed (status needs_ocr, analysis skipped) gets read and re-analyzed."""
    monkeypatch.setattr(llm, "vision", lambda *a, **k: REPORT)
    monkeypatch.setattr(llm, "chat_json", fake_json)
    data = png_bytes(page_image())
    with SessionLocal() as db:
        doc, _ = documents.save_upload(db, "old.png", data)
        jobs.enqueue_analyze(db, doc)
        old = db.query(jobs.Job).filter_by(kind="analyze").first()
        old.status, old.result = "done", {"skipped": "No readable text"}
        db.commit()
        assert jobs.enqueue_pending_ocr(db) == 1 and jobs.enqueue_pending_ocr(db) == 0
        jobs.run_pending(db)
    j = next(j for j in client.get("/api/jobs").json() if j["kind"] == "analyze")
    assert j["status"] == "done" and j["has_scan"]


def test_scan_analysis_waits_behind_text_work(client, monkeypatch):
    order = []
    monkeypatch.setattr(llm, "vision", lambda *a, **k: order.append("ocr") or REPORT)
    monkeypatch.setattr(llm, "chat_json", lambda s, i, **_: order.append("analyze") or fake_json(s, i))
    bulk(client, [("scan.png", png_bytes(page_image())), ("note.txt", b"Oncology OPD note dated 05-11-2026. Advised review.")])
    drain()
    assert order[0] == "analyze"  # the readable text note is analysed before the slow scan is read


def test_dense_page_falls_back_to_the_second_model(client, monkeypatch):
    """When the main model returns nothing for a page, the fallback model reads it."""
    used = []

    def vision(prompt, b64, model="", **_):
        used.append(model or "main")
        if not model:
            raise llm.LLMError("The model returned no transcription for this page (finish reason: length). Retry to read it again.")
        return "ECHOCARDIOGRAPHY report dated 26/12/24. LVEF 60%. Concentric LVH."

    monkeypatch.setattr(llm, "vision", vision)
    monkeypatch.setattr(llm, "chat_json", fake_json)
    bulk(client, [("echo.png", png_bytes(page_image()))])
    drain()
    assert used == ["main", "google/gemma-4-e2b"]
    d = client.get("/api/documents").json()[0]
    assert d["status"] == "indexed" and d["doc_date"] == "2024-12-26"


def test_connection_errors_do_not_trigger_the_fallback(client, monkeypatch):
    used = []

    def vision(prompt, b64, model="", **_):
        used.append(model or "main")
        raise llm.LLMError("Can't reach LM Studio.")

    monkeypatch.setattr(llm, "vision", vision)
    bulk(client, [("x.png", png_bytes(page_image()))])
    drain()
    assert used == ["main"]
    assert any(j["status"] == "failed" for j in client.get("/api/jobs").json())


def test_wrongly_unreadable_docs_are_retried(client, monkeypatch):
    """Pages recorded as blank because an earlier run got an empty model answer are read again."""
    monkeypatch.setattr(llm, "vision", lambda *a, **k: "Referral for adjuvant radiotherapy dated 12/01/25, Dr Pranav Bhatt.")
    monkeypatch.setattr(llm, "chat_json", fake_json)
    with SessionLocal() as db:
        doc, _ = documents.save_upload(db, "ref.png", png_bytes(page_image()))
        documents.index_page(db, doc, 1, ocr.BLANK_MARKER)
        doc.status = "unreadable"
        job = jobs.enqueue_ocr(db, doc)
        job.status = "done"
        db.commit()
        assert jobs.retry_unreadable(db) == 1
        jobs.run_pending(db)
    d = client.get("/api/documents").json()[0]
    assert d["status"] == "indexed" and d["doc_date"] == "2025-01-12"


def test_empty_model_answer_is_an_error_not_an_unreadable_page(monkeypatch):
    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"finish_reason": "length", "message": {"content": "", "reasoning_content": "thinking..."}}]}

    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: Resp())
    with pytest.raises(llm.LLMError, match="no transcription"):
        llm.vision("p", "abc")


def test_pages_needing_ocr_detection():
    assert documents.pages_needing_ocr(".pdf", ["Real text of a page that is long enough", "", "  "]) == [2, 3]
    assert documents.pages_needing_ocr(".png", []) == [1]
    assert documents.pages_needing_ocr(".txt", ["x"]) == []


def test_clean_transcript_collapses_runaway_repetition():
    noisy = "Header\n" + "same line\n" * 30 + "Footer"
    assert ocr.clean_transcript(noisy).splitlines() == ["Header", "same line", "same line", "Footer"]
    assert ocr.clean_transcript("```\nabc\n```") == "abc"


def test_chat_marks_ai_read_excerpts(client, monkeypatch):
    monkeypatch.setattr(llm, "vision", lambda *a, **k: REPORT)
    monkeypatch.setattr(llm, "chat_json", fake_json)
    bulk(client, [("scan.png", png_bytes(page_image()))])
    drain()
    seen = {}
    monkeypatch.setattr(llm, "chat", lambda s, i, **_: seen.setdefault("i", i) or "ok")
    client.post("/api/chat", json={"message": "How big is the tongue lesion?"})
    assert "AI-read scan" in seen["i"]
