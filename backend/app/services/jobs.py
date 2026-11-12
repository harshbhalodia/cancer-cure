"""Background queue for bulk uploads.

Uploads return immediately. A single worker thread then (1) ingests each file into the library, so it
is searchable at once, and (2) asks the local model for scan/case-file proposals, which wait in the
review inbox. The model is shared with chat, so the worker steps aside whenever an interactive
request is running, and resumes afterwards.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import case, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import ClinicalEvent, Document, DocumentChunk, Event, Job
from app.services import advisors, agent, casefile, documents, llm, ocr, recommendations, scan_extract, wellness

log = logging.getLogger("cc.jobs")

ALLOWED_SUFFIXES = {".pdf", ".txt", ".md", ".csv", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
MAX_BYTES = 50 * 1024 * 1024
SETTLE_SECONDS = 2  # ignore files still being copied into the inbox

_stop = threading.Event()
_thread: threading.Thread | None = None
_interactive = 0
_interactive_lock = threading.Lock()
_seen: dict[tuple[str, int, int], bool] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def interactive():
    """Wrap any user-facing model call so background work pauses between its own calls."""
    global _interactive
    with _interactive_lock:
        _interactive += 1
    try:
        yield
    finally:
        with _interactive_lock:
            _interactive -= 1


def _wait_for_user() -> None:
    while _interactive > 0 and not _stop.is_set():
        time.sleep(0.4)


# ------------------------------------------------------------------------------------ enqueue
def stage_bytes(filename: str, data: bytes) -> Path:
    staging = get_settings().staging_dir
    staging.mkdir(parents=True, exist_ok=True)
    path = staging / f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    path.write_bytes(data)
    return path


def known_hash(db: Session, sha: str) -> bool:
    return db.query(Document.id).filter_by(sha256=sha).first() is not None


def enqueue_ingest(db: Session, filename: str, path: Path, *, delete_after: bool) -> Job:
    job = Job(kind="ingest", filename=filename, payload={"path": str(path), "delete_after": delete_after})
    db.add(job)
    db.commit()
    return job


def enqueue_analyze(db: Session, doc: Document) -> Job | None:
    if db.query(Job.id).filter(Job.kind == "analyze", Job.document_id == doc.id).first():
        return None
    job = Job(kind="analyze", document_id=doc.id, filename=doc.filename)
    db.add(job)
    db.commit()
    return job


def requeue_analyze(db: Session, doc: Document) -> None:
    """After a scan has been read, (re)run analysis even if an earlier run skipped it for lack of text."""
    job = db.query(Job).filter(Job.kind == "analyze", Job.document_id == doc.id).first()
    if job is None:
        enqueue_analyze(db, doc)
        return
    job.status, job.result, job.error, job.review_status, job.finished_at = "queued", {}, "", "none", None
    db.commit()


def enqueue_ocr(db: Session, doc: Document) -> Job | None:
    if db.query(Job.id).filter(Job.kind == "ocr", Job.document_id == doc.id).first():
        return None
    job = Job(kind="ocr", document_id=doc.id, filename=doc.filename)
    db.add(job)
    db.commit()
    return job


def enqueue_unanalyzed(db: Session | None = None) -> int:
    """Queue analysis for readable documents that never had any (e.g. uploaded before the queue existed)."""
    own = db is None
    db = db or SessionLocal()
    try:
        n = 0
        for doc in db.query(Document).filter(Document.status == "indexed").all():
            if enqueue_analyze(db, doc):
                n += 1
        return n
    finally:
        if own:
            db.close()


def enqueue_journey_rebuild(db: Session | None = None) -> int:
    """Queue an events-only read of every readable document (used to rebuild the journey from scratch)."""
    own = db is None
    db = db or SessionLocal()
    try:
        n = 0
        for doc in db.query(Document).filter(Document.status == "indexed").all():
            existing = db.query(Job).filter(Job.kind == "journey", Job.document_id == doc.id).first()
            if existing is None:
                db.add(Job(kind="journey", document_id=doc.id, filename=doc.filename))
                n += 1
            elif existing.status in ("done", "failed"):
                existing.status, existing.error, existing.finished_at, existing.result = "queued", "", None, {}
                n += 1
        db.commit()
        return n
    finally:
        if own:
            db.close()


def _run_journey(db: Session, job: Job) -> None:
    """Add verified, quoted events from one document to the journey. Unlike case-file values, events never
    replace anything, each carries its source line, and you can remove or edit any of them."""
    doc = db.get(Document, job.document_id)
    if doc is None or doc.status != "indexed":
        job.result = {"skipped": "No readable text"}
        return
    _wait_for_user()
    events, rejected = agent.extract_events(db, doc)
    added = 0
    for e in events:
        if casefile.add_event(db, e["date"], e["category"], e["title"], e["detail"], "document", doc.id, e["quote"]):
            added += 1
    if added:
        db.add(Event(kind="case", title=f"Journey: {added} event(s) added from {doc.filename}", ref_type="document", ref_id=doc.id))
    job.result = {"added": added, "found": len(events), "rejected": len(rejected)}


def enqueue_actions(db: Session, doc: Document) -> Job | None:
    if db.query(Job.id).filter(Job.kind == "actions", Job.document_id == doc.id).first():
        return None
    job = Job(kind="actions", document_id=doc.id, filename=doc.filename)
    db.add(job)
    db.commit()
    return job


def enqueue_actions_rebuild(db: Session | None = None) -> int:
    """Queue a read for advisors' recommendations in every readable document (new ones are queued automatically)."""
    own = db is None
    db = db or SessionLocal()
    try:
        n = 0
        for doc in db.query(Document).filter(Document.status == "indexed").all():
            existing = db.query(Job).filter(Job.kind == "actions", Job.document_id == doc.id).first()
            if existing is None:
                db.add(Job(kind="actions", document_id=doc.id, filename=doc.filename))
                n += 1
            elif existing.status in ("done", "failed"):
                existing.status, existing.error, existing.finished_at, existing.result = "queued", "", None, {}
                n += 1
        db.commit()
        return n
    finally:
        if own:
            db.close()


def enqueue_plan(db: Session, pack_id: str) -> Job | None:
    for j in db.query(Job).filter(Job.kind == "plan", Job.status.in_(("queued", "running"))):
        if j.payload.get("pack_id") == pack_id:
            return None
    pack = advisors.load_packs().get(pack_id)
    job = Job(kind="plan", filename=pack.name if pack else pack_id, payload={"pack_id": pack_id})
    db.add(job)
    db.commit()
    return job


def enqueue_meds(db: Session, doc: Document, *, force: bool = False) -> Job | None:
    existing = db.query(Job).filter(Job.kind == "meds", Job.document_id == doc.id).first()
    if existing is not None:
        if force and existing.status in ("done", "failed"):
            existing.status, existing.error, existing.finished_at, existing.result = "queued", "", None, {}
            db.commit()
            return existing
        return None
    job = Job(kind="meds", document_id=doc.id, filename=doc.filename)
    db.add(job)
    db.commit()
    return job


def enqueue_meds_rebuild(db: Session) -> int:
    """Look for medicines in every readable document that could list some."""
    n = 0
    for doc in db.query(Document).filter(Document.status == "indexed").all():
        if wellness.worth_reading(scan_extract.document_text(db, doc), doc.doc_type) and enqueue_meds(db, doc, force=True):
            n += 1
    return n


def _run_meds(db: Session, job: Job) -> None:
    """Medicines a document tells the patient to take, quoted and shown as suggestions until you confirm each."""
    doc = db.get(Document, job.document_id)
    if doc is None or doc.status != "indexed":
        job.result = {"skipped": "No readable text"}
        return
    if not wellness.worth_reading(scan_extract.document_text(db, doc), doc.doc_type):
        job.result = {"skipped": "No medicines mentioned"}
        return
    _wait_for_user()
    found, rejected = wellness.extract_medicines(db, doc)
    added = wellness.add_found_medicines(db, doc, found)
    if added:
        db.add(Event(kind="case", title=f"Medicines: {added} found in {doc.filename} — confirm them in Today", ref_type="document", ref_id=doc.id))
    job.result = {"added": added, "found": len(found), "rejected": len(rejected)}


def _run_actions(db: Session, job: Job) -> None:
    """Add verified, quoted advisor recommendations from one document. Each carries its source line and advisor,
    and you can mark it done or dismiss it; the app adds no advice of its own."""
    doc = db.get(Document, job.document_id)
    if doc is None or doc.status != "indexed":
        job.result = {"skipped": "No readable text"}
        return
    _wait_for_user()
    found, rejected = recommendations.extract(db, doc)
    added = 0
    for r in found:
        if recommendations.add(db, document_id=doc.id, source="document", **r):
            added += 1
    if added:
        db.add(Event(kind="case", title=f"Recommendations: {added} found in {doc.filename}", ref_type="document", ref_id=doc.id))
    job.result = {"added": added, "found": len(found), "rejected": len(rejected)}
    db.commit()
    enqueue_meds(db, doc)


def _run_plan(db: Session, job: Job) -> None:
    pack = advisors.load_packs().get(job.payload.get("pack_id", ""))
    if pack is None:
        raise ValueError("This advisor pack is no longer available.")

    def progress(n: int, total: int, step: str) -> None:
        job.result = {"detail": f"step {n + 1} of {total}: {step}"}
        db.commit()

    run = advisors.run_pack(db, pack, progress=progress, wait=_wait_for_user)
    plan = advisors.save_plan(db, pack, run)
    db.add(Event(kind="case", title=f"Plan built: {pack.name}", detail="Built without the model (fallback)." if run.used_fallback else "", ref_type="plan", ref_id=plan.id))
    job.result = {"plan_id": plan.id, "fallback": run.used_fallback}


def retry_unreadable(db: Session) -> int:
    """Give documents that were wrongly recorded as unreadable another go (blank pages are re-detected
    cheaply without calling the model, so genuinely blank documents simply end up unreadable again)."""
    n = 0
    for doc in db.query(Document).filter(Document.status == "unreadable").all():
        for chunk in db.query(DocumentChunk).filter_by(document_id=doc.id, text=ocr.BLANK_MARKER).all():
            db.execute(text("DELETE FROM cc_chunk_fts WHERE chunk_id = :c"), {"c": chunk.id})
            db.delete(chunk)
        doc.status = "needs_ocr"
        job = db.query(Job).filter(Job.kind == "ocr", Job.document_id == doc.id).first()
        if job:
            job.status, job.error, job.finished_at, job.result = "queued", "", None, {}
        n += 1
    db.commit()
    return n


def enqueue_pending_ocr(db: Session | None = None) -> int:
    """Queue reading for every scanned document that has no OCR job yet (e.g. uploaded before OCR existed)."""
    own = db is None
    db = db or SessionLocal()
    try:
        n = 0
        for doc in db.query(Document).filter(Document.status == "needs_ocr").all():
            if enqueue_ocr(db, doc):
                n += 1
        return n
    finally:
        if own:
            db.close()


def submit_bytes(db: Session, filename: str, data: bytes) -> dict:
    """Queue one uploaded file. Returns a per-file outcome without doing any slow work."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        return {"filename": filename, "status": "unsupported", "detail": f"{suffix or 'this'} files can't be read"}
    if not data:
        return {"filename": filename, "status": "empty", "detail": "The file is empty"}
    if len(data) > MAX_BYTES:
        return {"filename": filename, "status": "too_large", "detail": "Larger than 50 MB"}
    if known_hash(db, hashlib.sha256(data).hexdigest()):
        return {"filename": filename, "status": "duplicate", "detail": "Already on file"}
    enqueue_ingest(db, filename, stage_bytes(filename, data), delete_after=True)
    return {"filename": filename, "status": "queued", "detail": ""}


def scan_inbox(db: Session | None = None) -> int:
    """Queue any new, settled files in the inbox folder. Files stay where they are."""
    inbox = get_settings().inbox_dir
    if not inbox.is_dir():
        return 0
    own = db is None
    db = db or SessionLocal()
    queued = 0
    try:
        for path in sorted(inbox.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            st = path.stat()
            key = (str(path), st.st_size, int(st.st_mtime))
            if key in _seen or time.time() - st.st_mtime < SETTLE_SECONDS or st.st_size == 0 or st.st_size > MAX_BYTES:
                continue
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            _seen[key] = True
            if known_hash(db, sha):
                continue
            enqueue_ingest(db, path.name, path, delete_after=False)
            queued += 1
    finally:
        if own:
            db.close()
    return queued


# ------------------------------------------------------------------------------------ execution
def _run_ingest(db: Session, job: Job) -> None:
    path = Path(job.payload["path"])
    try:
        doc, created = documents.save_upload(db, job.filename, path.read_bytes())
    finally:
        if job.payload.get("delete_after"):
            path.unlink(missing_ok=True)
    job.document_id = doc.id
    job.result = {"created": created, "status": doc.status, "doc_type": doc.doc_type}
    if created:
        if doc.status == "needs_ocr":
            enqueue_ocr(db, doc)
        else:
            enqueue_analyze(db, doc)
            enqueue_actions(db, doc)


def _run_ocr(db: Session, job: Job) -> None:
    doc = db.get(Document, job.document_id)
    if doc is None:
        job.result = {"skipped": "The document was removed"}
        return

    def progress(done: int, total: int) -> None:
        job.result = {"pages_done": done, "pages_total": total}
        db.commit()

    job.result = {"pages_done": 0, "pages_total": 0}
    summary = ocr.read_document(db, doc, progress=progress, wait=_wait_for_user)
    job.result = {**summary, "pages_done": summary["pages_read"], "pages_total": summary["pages_read"]}
    if doc.status == "indexed":
        requeue_analyze(db, doc)
        enqueue_actions(db, doc)


def _has_content(proposal: dict | None) -> bool:
    return bool(proposal and (proposal["lesions"] or proposal["findings"] or proposal["reported_response"]["label"]))


def _run_analyze(db: Session, job: Job) -> None:
    doc = db.get(Document, job.document_id)
    if doc is None:
        job.result = {"skipped": "The document was removed"}
        return
    if doc.status != "indexed":
        job.result = {"skipped": "No readable text could be found on the page(s)"}
        return
    scan = None
    if doc.doc_type == "imaging":
        _wait_for_user()
        scan = scan_extract.extract(db, doc)
    _wait_for_user()
    proposal = _new_information(db, agent.extract_case_fields(db, doc))
    scan = scan if _has_content(scan) else None
    job.result = {"scan": scan, "case": proposal, "reviewed": {}}
    job.review_status = "pending" if (scan or proposal) else "none"


def _new_information(db: Session, extracted: dict) -> dict | None:
    """Keep only what would add something: values that differ from the current case file and events not already in the journey."""
    values, _ = casefile.derive(db)
    fields = {}
    for key, value in extracted["fields"].items():
        have = casefile.norm(values.get(key, ""))
        if value and casefile.norm(value) != have and casefile.norm(value) not in have:
            fields[key] = value
    known = {(e.event_date, e.category, casefile.norm(e.title)) for e in db.query(ClinicalEvent).all()}
    events = [e for e in extracted["events"] if (e["date"], e["category"], casefile.norm(e["title"])) not in known]
    if not fields and not events:
        return None
    return {"fields": fields, "as_of": extracted["as_of"], "events": events, "rejected": extracted["rejected"]}


def run_one(db: Session) -> bool:
    """Run the next queued job: ingests first (every file appears fast), then analysis of readable
    documents, then the slow page-by-page reading of scans. Returns False if idle."""
    priority = case((Job.kind.in_(("ingest", "plan")), 0), (Job.kind.in_(("analyze", "journey", "actions", "meds")), 1), else_=2)
    job = db.query(Job).filter(Job.status == "queued").order_by(priority, Job.id).first()
    if job is None:
        return False
    job.status, job.started_at, job.attempts, job.error = "running", _now(), job.attempts + 1, ""
    db.commit()
    runner = {"ingest": _run_ingest, "analyze": _run_analyze, "ocr": _run_ocr, "journey": _run_journey,
              "actions": _run_actions, "meds": _run_meds, "plan": _run_plan}[job.kind]
    try:
        runner(db, job)
        job.status = "done"
    except llm.LLMError as exc:
        db.rollback()
        job = db.get(Job, job.id)
        job.status, job.error = "failed", str(exc)
    except Exception as exc:  # corrupt file etc.: record and move on
        db.rollback()
        log.exception("job %s failed", job.id)
        job = db.get(Job, job.id)
        job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"[:500]
    job.finished_at = _now()
    db.commit()
    return True


def run_pending(db: Session) -> int:
    """Synchronously drain the queue (used by tests and the CLI-free fallback)."""
    n = 0
    while run_one(db):
        n += 1
    return n


def reset_stale() -> None:
    with SessionLocal() as db:
        for job in db.query(Job).filter(Job.status == "running").all():
            job.status = "queued"
        db.commit()


def _loop() -> None:
    reset_stale()
    try:
        with SessionLocal() as db:
            retry_unreadable(db)
            for doc in db.query(Document).filter(Document.text_source == "vision_ocr", Document.status == "indexed").all():
                documents.refresh_metadata(db, doc)  # re-apply the latest classifier to already-read scans
            db.commit()
        enqueue_pending_ocr()
        enqueue_unanalyzed()
        with SessionLocal() as db:
            for doc in db.query(Document).filter(Document.status == "indexed").all():
                enqueue_actions(db, doc)  # documents that predate recommendation tracking
                enqueue_meds(db, doc)  # and medicine tracking
    except Exception:
        log.exception("could not queue pending OCR")
    last_scan = 0.0
    interval = get_settings().watch_interval_s
    while not _stop.is_set():
        try:
            if time.monotonic() - last_scan >= interval:
                scan_inbox()
                last_scan = time.monotonic()
            with SessionLocal() as db:
                busy = run_one(db)
            if not busy:
                _stop.wait(1.0)
        except Exception:
            log.exception("worker loop error")
            _stop.wait(3.0)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="cc-worker", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    if _thread:
        _thread.join(timeout=5)


def cleanup_staging() -> None:
    """Remove staged files whose ingest job no longer exists (e.g. after a crash)."""
    staging = get_settings().staging_dir
    if not staging.is_dir():
        return
    with SessionLocal() as db:
        live = {j.payload.get("path") for j in db.query(Job).filter(Job.kind == "ingest", Job.status.in_(("queued", "running"))).all()}
    for f in staging.iterdir():
        if str(f) not in live:
            f.unlink(missing_ok=True)
    if not any(staging.iterdir()):
        shutil.rmtree(staging, ignore_errors=True)
