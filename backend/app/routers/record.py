from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, Event, Fact, Finding, Measurement, Scan
from app.services import jobs, llm, readiness, scan_extract
from app.services import requirements as req

router = APIRouter(prefix="/api")


# ---- scans --------------------------------------------------------------------------------
@router.post("/documents/{doc_id}/extract-scan")
def extract_scan(doc_id: int, db: Session = Depends(get_db)) -> dict:
    doc = db.get(Document, doc_id) or _missing()
    try:
        with jobs.interactive():
            return scan_extract.extract(db, doc)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc


class LesionIn(BaseModel):
    name: str
    site: str = ""
    is_target: bool = True
    basis: str = "unknown"
    size_mm_now: float | None = None
    size_mm_prior: float | None = None
    suv_max_now: float | None = None
    quote: str = ""


class FindingIn(BaseModel):
    text: str
    category: str = "other"
    certainty: str = "possible"
    quote: str = ""


class ScanIn(BaseModel):
    modality: str = ""
    date: str = ""
    comparator_modality: str = ""
    comparator_date: str = ""
    lesions: list[LesionIn] = Field(default_factory=list)
    findings: list[FindingIn] = Field(default_factory=list)
    reported_label: str = ""
    reported_criteria: str = ""
    reported_sum_prior: float | None = None
    reported_sum_now: float | None = None
    reported_pct: float | None = None
    reported_quote: str = ""


@router.post("/documents/{doc_id}/scan")
def save_scan(doc_id: int, body: ScanIn, db: Session = Depends(get_db)) -> dict:
    doc = db.get(Document, doc_id) or _missing()
    text = scan_extract.document_text(db, doc)
    for q in [l.quote for l in body.lesions] + [f.quote for f in body.findings]:
        if not scan_extract.quote_supported(q, text):
            raise HTTPException(422, "A quoted source line does not match the document; please re-read the report.")
    if not body.lesions and not body.findings and not body.reported_label:
        raise HTTPException(422, "Nothing to save.")

    existing = db.query(Scan).filter_by(document_id=doc.id).first()
    if existing:
        db.delete(existing)
        db.flush()
    scan_date = body.date or doc.doc_date
    scan = Scan(
        document_id=doc.id, modality=body.modality, scan_date=scan_date,
        comparator_date=body.comparator_date, comparator_modality=body.comparator_modality,
        reported_label=body.reported_label, reported_criteria=body.reported_criteria,
        reported_sum_prior=body.reported_sum_prior, reported_sum_now=body.reported_sum_now,
        reported_pct=body.reported_pct, reported_quote=body.reported_quote,
    )
    db.add(scan)
    db.flush()
    for l in body.lesions:
        key = scan_extract.norm_key(l.name)
        common = dict(scan_id=scan.id, lesion=key, label=l.name.strip(), site=l.site, is_target=l.is_target, basis=l.basis, quote=l.quote)
        if l.size_mm_now is not None:
            db.add(Measurement(**common, point_date=scan_date, kind="current", size_mm=l.size_mm_now, suv_max=l.suv_max_now))
        if l.size_mm_prior is not None:
            db.add(Measurement(**common, point_date=body.comparator_date, kind="prior", size_mm=l.size_mm_prior))
    for f in body.findings:
        db.add(Finding(scan_id=scan.id, text=f.text, category=f.category, certainty=f.certainty, quote=f.quote))
    if doc.doc_type != "imaging":
        doc.doc_type = "imaging"
    if scan_date and not doc.doc_date:
        doc.doc_date = scan_date
    db.add(Event(kind="scan", title=f"Scan data confirmed ({body.modality or 'imaging'} {scan_date})",
                 detail=f"{len(body.lesions)} lesion(s), {len(body.findings)} finding(s) from {doc.filename}", ref_type="document", ref_id=doc.id))
    db.commit()
    return readiness.progress(db)


@router.delete("/documents/{doc_id}/scan", status_code=204)
def delete_scan(doc_id: int, db: Session = Depends(get_db)) -> None:
    scan = db.query(Scan).filter_by(document_id=doc_id).first() or _missing()
    db.delete(scan)
    db.commit()


@router.get("/progress")
def get_progress(db: Session = Depends(get_db)) -> dict:
    return readiness.progress(db)


# ---- facts / readiness ---------------------------------------------------------------------
class FactIn(BaseModel):
    status: str
    value: str = ""
    fact_date: str = ""
    document_id: int | None = None
    quote: str = ""


@router.put("/facts/{key}")
def put_fact(key: str, body: FactIn, db: Session = Depends(get_db)) -> dict:
    if key not in req.BY_KEY:
        raise HTTPException(404, "Unknown record item.")
    if body.status not in ("present", "negative", "not_done"):
        raise HTTPException(422, "Status must be present, negative or not_done.")
    if body.status == "present" and not body.value.strip():
        raise HTTPException(422, "Enter the value or result.")
    fact = db.query(Fact).filter_by(key=key).first() or Fact(key=key)
    fact.status, fact.value, fact.fact_date = body.status, body.value.strip(), body.fact_date
    fact.document_id, fact.quote = body.document_id, body.quote
    db.add(fact)
    db.add(Event(kind="record", title=f"{req.BY_KEY[key].label}: {body.status.replace('_', ' ')}", detail=body.value.strip()[:300]))
    db.commit()
    return {"ok": True}


@router.delete("/facts/{key}", status_code=204)
def delete_fact(key: str, db: Session = Depends(get_db)) -> None:
    fact = db.query(Fact).filter_by(key=key).first() or _missing()
    db.delete(fact)
    db.commit()


@router.get("/readiness")
def get_readiness(db: Session = Depends(get_db)) -> dict:
    return {**readiness.readiness(db), "insights": readiness.insights(db)}


def _missing():
    raise HTTPException(404, "Not found.")
