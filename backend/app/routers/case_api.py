from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CaseEntry, ClinicalEvent, Document, Event
from app.services import casefile, jobs, llm

router = APIRouter(prefix="/api")


def _flat(db: Session) -> dict[str, str]:
    values, _ = casefile.derive(db)
    return values


@router.get("/case")
def get_case(db: Session = Depends(get_db)) -> dict:
    """Current case file: for each field, the latest dated information."""
    return _flat(db)


@router.get("/case/detail")
def get_case_detail(db: Session = Depends(get_db)) -> dict:
    return casefile.detail(db)


@router.put("/case")
def put_case(body: dict[str, str], db: Session = Depends(get_db)) -> dict:
    """Save edits made on the form. Only changed fields are recorded, as new entries dated today; nothing is overwritten."""
    unknown = [k for k in body if k not in casefile.KIND]
    if unknown:
        raise HTTPException(422, f"Unknown field(s): {', '.join(unknown)}")
    casefile.save_user_edits(db, body)
    return _flat(db)


class EntryIn(BaseModel):
    field: str
    value: str
    as_of: str = ""
    document_id: int | None = None
    quote: str = ""


class EventIn(BaseModel):
    date: str = ""
    category: str = "other"
    title: str
    detail: str = ""
    quote: str = ""


class ProposalIn(BaseModel):
    document_id: int | None = None
    as_of: str = ""
    fields: dict[str, str] = Field(default_factory=dict)
    events: list[EventIn] = Field(default_factory=list)


@router.post("/case/apply")
def apply_proposal(body: ProposalIn, db: Session = Depends(get_db)) -> dict:
    """Store a reviewed document proposal as dated history. Newer information stays current; older goes to history."""
    doc = db.get(Document, body.document_id) if body.document_id else None
    if doc is None:
        raise HTTPException(404, "Document not found.")
    for e in body.events:
        if e.quote and not _quote_ok(db, doc, e.quote):
            raise HTTPException(422, "A quoted source line does not match the document; please re-read it.")
    result = casefile.apply_proposal(db, doc, body.fields, body.as_of, [e.model_dump() for e in body.events])
    return {**result, "case": _flat(db)}


def _quote_ok(db: Session, doc: Document, quote: str) -> bool:
    from app.services import scan_extract

    return scan_extract.quote_supported(quote, scan_extract.document_text(db, doc))


@router.post("/case/entries")
def add_user_entry(body: EntryIn, db: Session = Depends(get_db)) -> dict:
    """Add your own dated entry (e.g. a new line of treatment history)."""
    if body.field not in casefile.KIND:
        raise HTTPException(404, "Unknown field.")
    if not body.value.strip():
        raise HTTPException(422, "Enter a value.")
    casefile.add_entry(db, body.field, body.value, body.as_of or casefile.today(), "you")
    casefile.recompute(db)
    db.add(Event(kind="case", title="Case file updated", detail=f"Added to {casefile.LABELS[body.field]}", ref_type="case", ref_id=1))
    db.commit()
    return casefile.detail(db)


class DateIn(BaseModel):
    as_of: str


@router.patch("/case/entries/{entry_id}")
def set_entry_date(entry_id: int, body: DateIn, db: Session = Depends(get_db)) -> dict:
    """Set or correct the date an entry was true (e.g. an old value that has no date yet)."""
    entry = db.get(CaseEntry, entry_id) or _missing()
    if body.as_of:
        try:
            date.fromisoformat(body.as_of)
        except ValueError as exc:
            raise HTTPException(422, "Use a date like 2026-11-02.") from exc
    entry.as_of = body.as_of
    casefile.recompute(db)
    db.commit()
    return casefile.detail(db)


@router.delete("/case/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int, db: Session = Depends(get_db)) -> None:
    entry = db.get(CaseEntry, entry_id) or _missing()
    db.delete(entry)
    casefile.recompute(db)
    db.add(Event(kind="case", title="History entry removed", detail=f"{casefile.LABELS.get(entry.field, entry.field)} as of {entry.as_of or 'unknown date'}", ref_type="case", ref_id=1))
    db.commit()


@router.post("/case/events")
def add_user_event(body: EventIn, db: Session = Depends(get_db)) -> dict:
    ev = casefile.add_event(db, body.date, body.category, body.title, body.detail, "you")
    if ev is None:
        raise HTTPException(409, "That event is already in the journey (or the title is empty).")
    db.add(Event(kind="case", title=f"Journey: {ev.title}", detail=ev.event_date or "date unknown", ref_type="case", ref_id=1))
    db.commit()
    return casefile.detail(db)


class EventPatch(BaseModel):
    date: str | None = None
    title: str | None = None
    category: str | None = None
    detail: str | None = None


@router.patch("/case/events/{event_id}")
def edit_event(event_id: int, body: EventPatch, db: Session = Depends(get_db)) -> dict:
    """Correct an event's date, title, type or detail (e.g. give an undated event its date)."""
    if body.date:
        try:
            date.fromisoformat(body.date)
        except ValueError as exc:
            raise HTTPException(422, "Use a date like 2026-11-02.") from exc
    if body.category is not None and body.category not in casefile.EVENT_CATEGORIES:
        raise HTTPException(422, "Unknown event type.")
    if casefile.update_event(db, event_id, event_date=body.date, title=body.title, category=body.category, detail=body.detail) is None:
        raise HTTPException(404, "Not found.")
    return casefile.detail(db)


@router.delete("/case/events/{event_id}", status_code=204)
def delete_event(event_id: int, db: Session = Depends(get_db)) -> None:
    ev = db.get(ClinicalEvent, event_id) or _missing()
    db.delete(ev)
    db.commit()


@router.post("/case/rebuild-journey")
def rebuild_journey(db: Session = Depends(get_db)) -> dict:
    """Read every document again for dated events only. Events are verified against the document, never replace
    anything, and can be edited or removed. Runs in the background."""
    return {"queued": jobs.enqueue_journey_rebuild(db)}


@router.post("/case/summary")
def generate_summary(db: Session = Depends(get_db)) -> dict:
    try:
        with jobs.interactive():
            return casefile.generate_summary(db)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc


def _missing():
    raise HTTPException(404, "Not found.")
