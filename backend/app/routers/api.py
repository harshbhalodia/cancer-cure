from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import ChatMessage, Document, Event
from app.services import agent, documents, jobs, llm

router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


# ---- health -------------------------------------------------------------------------------
@router.get("/health")
def health() -> dict:
    return {"ok": True, "llm": llm.status(), "emergency_number": get_settings().emergency_number}


# ---- case file (history-based; see routers/case_api.py) ------------------------------------


# ---- documents ----------------------------------------------------------------------------
def _doc_dict(d: Document) -> dict:
    return {
        "id": d.id, "filename": d.filename, "doc_type": d.doc_type, "doc_date": d.doc_date,
        "page_count": d.page_count, "text_chars": d.text_chars, "status": d.status, "text_source": d.text_source,
        "created_at": d.created_at.isoformat(),
    }


@router.get("/documents")
def list_documents(db: Session = Depends(get_db)) -> list[dict]:
    docs = db.query(Document).order_by(Document.doc_date.desc(), Document.id.desc()).all()
    return [_doc_dict(d) for d in docs]


@router.post("/documents")
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(400, "The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The file is larger than 50 MB.")
    try:
        doc, created = documents.save_upload(db, file.filename or "upload", data)
    except Exception as exc:  # unreadable/corrupt PDF
        raise HTTPException(422, f"Could not read this file: {exc}") from exc
    return {**_doc_dict(doc), "already_uploaded": not created}


@router.patch("/documents/{doc_id}")
def update_document(doc_id: int, body: dict, db: Session = Depends(get_db)) -> dict:
    doc = db.get(Document, doc_id) or _missing()
    for key in ("doc_type", "doc_date", "source"):
        if key in body and isinstance(body[key], str):
            setattr(doc, key, body[key][:200])
    db.commit()
    return _doc_dict(doc)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int, db: Session = Depends(get_db)) -> None:
    documents.delete_document(db, db.get(Document, doc_id) or _missing())


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: int, db: Session = Depends(get_db)) -> FileResponse:
    doc = db.get(Document, doc_id) or _missing()
    return FileResponse(get_settings().uploads_dir / doc.stored_name, filename=doc.filename)


@router.post("/documents/{doc_id}/extract-case")
def extract_case(doc_id: int, db: Session = Depends(get_db)) -> dict:
    doc = db.get(Document, doc_id) or _missing()
    try:
        with jobs.interactive():
            return {"proposed": (r := agent.extract_case_fields(db, doc))["fields"], **r}
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc


# ---- chat ---------------------------------------------------------------------------------
class ChatIn(BaseModel):
    message: str
    role: str = "patient"


@router.post("/chat")
def chat(body: ChatIn, db: Session = Depends(get_db)) -> dict:
    if not body.message.strip():
        raise HTTPException(400, "Message is empty.")
    with jobs.interactive():
        reply = agent.answer(db, body.message.strip(), body.role)
    return {"content": reply.content, "citations": reply.citations, "flags": reply.flags}


@router.get("/chat")
def chat_history(limit: int = 100, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(ChatMessage).order_by(ChatMessage.id.desc()).limit(limit).all()[::-1]
    return [
        {"id": m.id, "ts": m.ts.isoformat(), "role": m.role, "content": m.content, "citations": m.citations, "flags": m.flags}
        for m in rows
    ]


# ---- timeline -----------------------------------------------------------------------------
@router.get("/timeline")
def timeline(limit: int = 200, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Event).order_by(Event.ts.desc(), Event.id.desc()).limit(limit).all()
    return [
        {"id": e.id, "ts": e.ts.isoformat(), "kind": e.kind, "title": e.title, "detail": e.detail,
         "ref_type": e.ref_type, "ref_id": e.ref_id}
        for e in rows
    ]


def _missing():
    raise HTTPException(404, "Not found.")
