from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, Job
from app.services import jobs

router = APIRouter(prefix="/api")


@router.post("/documents/bulk")
async def bulk_upload(files: list[UploadFile] = File(...), db: Session = Depends(get_db)) -> dict:
    """Accepts any number of files and returns as soon as they are queued; processing continues in the background."""
    results = [jobs.submit_bytes(db, f.filename or "upload", await f.read()) for f in files]
    return {"queued": sum(r["status"] == "queued" for r in results), "results": results}


@router.post("/inbox/scan")
def scan_inbox_now() -> dict:
    return {"queued": jobs.scan_inbox()}


def _job_dict(j: Job) -> dict:
    result = j.result or {}
    reviewed = result.get("reviewed", {})
    return {
        "id": j.id, "kind": j.kind, "status": j.status, "filename": j.filename, "document_id": j.document_id,
        "error": j.error, "review_status": j.review_status, "attempts": j.attempts,
        "created_at": j.created_at.isoformat(), "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        "skipped": result.get("skipped", ""),
        "added": result.get("added"),
        "progress": f"page {result['pages_done']} of {result['pages_total']}" if result.get("pages_total") and j.status == "running" else "",
        "has_scan": bool(result.get("scan")) and not reviewed.get("scan"),
        "has_case": bool(result.get("case")) and not reviewed.get("case"),
    }


@router.get("/jobs/summary")
def summary(db: Session = Depends(get_db)) -> dict:
    counts = dict(db.query(Job.status, func.count()).group_by(Job.status).all())
    running = db.query(Job).filter(Job.status == "running").first()
    return {
        "queued": counts.get("queued", 0), "running": counts.get("running", 0),
        "done": counts.get("done", 0), "failed": counts.get("failed", 0),
        "pending_review": db.query(func.count(Job.id)).filter(Job.review_status == "pending").scalar(),
        "current": {"kind": running.kind, "filename": running.filename,
                    "detail": (f"page {running.result['pages_done'] + 1} of {running.result['pages_total']}"
                               if running.kind == "ocr" and (running.result or {}).get("pages_total")
                               else (running.result or {}).get("detail", ""))} if running else None,
    }


@router.post("/documents/ocr-pending")
def ocr_pending() -> dict:
    return {"queued": jobs.enqueue_pending_ocr()}


@router.get("/jobs")
def list_jobs(limit: int = 200, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Job).order_by(Job.id.desc()).limit(limit).all()
    return [_job_dict(j) for j in rows]


@router.get("/jobs/{job_id}/result")
def job_result(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id) or _missing()
    result = job.result or {}
    reviewed = result.get("reviewed", {})
    case = None if reviewed.get("case") else result.get("case")
    if case and "fields" not in case:  # suggestion produced before the case file kept history
        doc = db.get(Document, job.document_id) if job.document_id else None
        case = {"fields": case, "as_of": doc.doc_date if doc else "", "events": [], "rejected": []}
    return {"scan": None if reviewed.get("scan") else result.get("scan"), "case": case, "document_id": job.document_id}


class Resolve(BaseModel):
    part: str  # scan | case


@router.post("/jobs/{job_id}/resolve")
def resolve(job_id: int, body: Resolve, db: Session = Depends(get_db)) -> dict:
    """Mark one proposal as handled (saved or dismissed); the job leaves the inbox when none remain."""
    if body.part not in ("scan", "case"):
        raise HTTPException(422, "part must be scan or case")
    job = db.get(Job, job_id) or _missing()
    result = dict(job.result or {})
    reviewed = dict(result.get("reviewed", {}))
    reviewed[body.part] = True
    result["reviewed"] = reviewed
    job.result = result
    if all(reviewed.get(p) or not result.get(p) for p in ("scan", "case")):
        job.review_status = "reviewed"
    db.commit()
    return _job_dict(job)


@router.post("/jobs/{job_id}/retry")
def retry(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id) or _missing()
    if job.status != "failed":
        raise HTTPException(409, "Only failed jobs can be retried.")
    job.status, job.error, job.finished_at = "queued", "", None
    db.commit()
    return _job_dict(job)


@router.post("/jobs/retry-failed")
def retry_failed(db: Session = Depends(get_db)) -> dict:
    n = db.query(Job).filter(Job.status == "failed").update({"status": "queued", "error": "", "finished_at": None})
    db.commit()
    return {"requeued": n}


def _missing():
    raise HTTPException(404, "Not found.")
