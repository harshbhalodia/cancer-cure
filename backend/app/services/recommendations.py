"""Advisors' recommendations: what each clinician or report advised, tracked until it is done.

The model only *finds* them in documents. Each one must be backed by a verbatim quote, keeps the
advisor's name and the date, and is shown as quoted advice — the app never adds medical advice of its own.
You set the status (open / done / dismissed); the app adds a hint when the journey already contains a
later event of the matching kind ("possibly already done").
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import ClinicalEvent, Document, Recommendation, Scan
from app.services import casefile, llm, scan_extract
from app.services.prompts import RECS_SYSTEM

CATEGORIES = (
    "test", "imaging", "biopsy", "surgery", "radiotherapy", "chemotherapy", "immunotherapy",
    "referral", "follow_up", "supportive", "lifestyle", "other",
)
CERTAINTY = ("advised", "planned", "suggested", "considered")
# which kind of journey event would show that a recommendation has been acted on
ADDRESSED_BY = {
    "imaging": "imaging", "biopsy": "biopsy", "surgery": "surgery", "radiotherapy": "radiotherapy",
    "chemotherapy": "chemotherapy", "immunotherapy": "immunotherapy", "test": "lab",
    "referral": "consultation", "follow_up": "consultation",
}
STALE_DAYS = 365


def _now() -> datetime:
    return datetime.now(timezone.utc)


def add(db: Session, *, text: str, category: str = "other", advisor: str = "", rec_date: str = "", target_date: str = "",
        timing: str = "", certainty: str = "advised", source: str = "document", document_id: int | None = None,
        quote: str = "") -> Recommendation | None:
    text = (text or "").strip()
    if not text:
        return None
    category = category if category in CATEGORIES else "other"
    for r in db.query(Recommendation).filter_by(category=category):
        near = not r.rec_date or not rec_date or r.rec_date == rec_date
        if near and (casefile.norm(r.text) == casefile.norm(text) or casefile._similar(r.text, text)):
            return None
    rec = Recommendation(
        text=text, category=category, advisor=(advisor or "").strip()[:200], rec_date=rec_date or "", target_date=target_date or "",
        timing=(timing or "").strip()[:120], certainty=certainty if certainty in CERTAINTY else "advised", source=source,
        document_id=document_id, quote=quote,
    )
    db.add(rec)
    db.flush()
    return rec


def extract(db: Session, doc: Document) -> tuple[list[dict], list[dict]]:
    """Recommendations in one document, verified: the quote must be in the text; unseen dates are dropped."""
    text = scan_extract.document_text(db, doc)
    if not text.strip():
        raise llm.LLMError("This document has no readable text yet.")
    data = llm.chat_json(RECS_SYSTEM, f"DOCUMENT ({doc.filename}, {doc.doc_date or 'date unknown'}):\n{text[:12000]}")
    dates = scan_extract.find_dates(text) | ({doc.doc_date} if doc.doc_date else set())
    kept, rejected = [], []
    for raw in data.get("recommendations") or []:
        if not isinstance(raw, dict):
            continue
        body, quote = str(raw.get("text") or "").strip(), str(raw.get("quote") or "")
        if len(body.split()) < 2:
            rejected.append({"item": body[:60] or "?", "reason": "too vague to be useful on its own"})
            continue
        if not body or not scan_extract.quote_supported(quote, text):
            rejected.append({"item": body[:60] or "?", "reason": "quote not found in the document"})
            continue
        when = str(raw.get("date") or "").strip()
        if when not in dates:
            when = doc.doc_date or ""
        target = str(raw.get("target_date") or "").strip()
        if target and target not in dates:
            target = ""
        kept.append({
            "text": body, "category": raw.get("category") if raw.get("category") in CATEGORIES else "other",
            "advisor": str(raw.get("advisor") or "").strip(), "rec_date": when, "target_date": target,
            "timing": str(raw.get("timing") or "").strip(),
            "certainty": raw.get("certainty") if raw.get("certainty") in CERTAINTY else "advised", "quote": quote,
        })
    return kept, rejected


def hint_events(db: Session) -> list[tuple[str, str, str]]:
    """(category, date, title) of everything that shows something was done: journey events and confirmed scans."""
    out = [(e.category, e.event_date, e.title) for e in db.query(ClinicalEvent).all() if e.event_date]
    out += [("imaging", s.scan_date, f"{s.modality or 'imaging'} scan") for s in db.query(Scan).all() if s.scan_date]
    return out


def addressed_by(db: Session, rec: Recommendation, events: list[tuple[str, str, str]] | None = None) -> list[dict]:
    """Later events of the matching kind: a hint (never a decision) that this may already have been done."""
    kind = ADDRESSED_BY.get(rec.category)
    if not kind or not rec.rec_date:
        return []
    events = events if events is not None else hint_events(db)
    later = sorted({(d, t) for c, d, t in events if c == kind and d > rec.rec_date})
    return [{"date": d, "title": t} for d, t in later[:2]]


def age_days(rec: Recommendation, today: datetime | None = None) -> int | None:
    if not rec.rec_date:
        return None
    try:
        return ((today or _now()).date() - datetime.fromisoformat(rec.rec_date).date()).days
    except ValueError:
        return None


def as_dict(db: Session, rec: Recommendation, docs: dict[int, str], events: list[tuple[str, str, str]]) -> dict:
    return {
        "id": rec.id, "text": rec.text, "category": rec.category, "advisor": rec.advisor, "rec_date": rec.rec_date,
        "target_date": rec.target_date, "timing": rec.timing, "certainty": rec.certainty, "status": rec.status,
        "note": rec.note, "source": rec.source, "document_id": rec.document_id, "filename": docs.get(rec.document_id, ""),
        "quote": rec.quote, "addressed_by": addressed_by(db, rec, events) if rec.status == "open" else [],
        "age_days": age_days(rec),
    }


def listing(db: Session) -> list[dict]:
    docs = {d.id: d.filename for d in db.query(Document).all()}
    events = hint_events(db)
    rows = db.query(Recommendation).all()
    rows.sort(key=lambda r: (r.status != "open", -(int((r.rec_date or "0000-00-00").replace("-", "")) or 0), r.id))
    return [as_dict(db, r, docs, events) for r in rows]


def set_status(db: Session, rec_id: int, status: str, note: str | None = None) -> Recommendation | None:
    rec = db.get(Recommendation, rec_id)
    if rec is None:
        return None
    rec.status = status
    rec.resolved_at = _now() if status != "open" else None
    if note is not None:
        rec.note = note.strip()
    db.commit()
    return rec


def context_lines(db: Session, limit: int = 25) -> str:
    """Open recommendations as compact, citable lines for the assistant and the advisor packs ([R#] tags)."""
    items = [r for r in listing(db) if r["status"] == "open"][:limit]
    lines = []
    for r in items:
        who = r["advisor"] or "an advisor"
        hint = f" (a later {r['addressed_by'][0]['title']} on {r['addressed_by'][0]['date']} may mean this was done)" if r["addressed_by"] else ""
        when = r["rec_date"] or "date unknown"
        timing = f", timing: {r['timing']}" if r["timing"] else ""
        lines.append(f"- [R{r['id']}] {when}, {who} ({r['category']}, {r['certainty']}{timing}): {r['text']}{hint}")
    return "\n".join(lines)
