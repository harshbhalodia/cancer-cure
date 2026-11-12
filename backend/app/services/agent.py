"""One chat turn: triage → context pack → model → lint → citation check → persist."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AgentRun, Case, ChatMessage, Document, Event
from app.services import casefile, llm, readiness, recommendations, retrieval, safety, wellness
from app.services.prompts import EVENTS_SYSTEM, EXTRACT_KEYS, EXTRACT_SYSTEM, PROMPT_VERSION, ROLE_NOTES, SYSTEM_PROMPT

HISTORY_TURNS = 8
CONTEXT_CHAR_BUDGET = 7000
_TAG = re.compile(r"D(\d+)(?:\s*p(\d+))?")
_CITATION = re.compile(r"\[(D\d+(?:\s*p\d+)?(?:\s*[,;]\s*D\d+(?:\s*p\d+)?)*)\]")

CASE_FIELDS = (
    ("patient_name", "Name"), ("age", "Age"), ("sex", "Sex"), ("diagnosis", "Diagnosis"),
    ("primary_site", "Primary site"), ("histology", "Histology"), ("stage", "Stage"),
    ("biomarkers", "Biomarkers"), ("hla_type", "HLA type"), ("treatment_history", "Treatment history"),
    ("current_treatment", "Current treatment"), ("current_status", "Current status"),
    ("allergies", "Allergies"), ("care_team", "Care team"), ("goals", "Goals"), ("notes", "Notes"),
)


@dataclass
class Reply:
    content: str
    citations: list[dict] = field(default_factory=list)
    flags: list[dict] = field(default_factory=list)


def case_summary(case: Case | None) -> str:
    if case is None:
        return "(The case file is empty. Ask the user for the basics: diagnosis, stage, current treatment.)"
    lines = [f"- {label}: {getattr(case, key)}" for key, label in CASE_FIELDS if getattr(case, key)]
    return "\n".join(lines) or "(The case file is empty. Ask the user for the basics: diagnosis, stage, current treatment.)"


def _passage_block(passages: list[retrieval.Passage]) -> str:
    out, used = [], 0
    for p in passages:
        block = f"[D{p.document_id} p{p.page}] ({p.filename}, {p.doc_date or 'date unknown'}{', AI-read scan: may contain reading errors' if p.ai_read else ''})\n{p.text}"
        if used + len(block) > CONTEXT_CHAR_BUDGET:
            break
        out.append(block)
        used += len(block)
    return "\n\n".join(out) or "(no matching document excerpts)"


def _insight_lines(db: Session) -> str:
    items = readiness.insights(db)[:8]
    return "\n".join(f"- [{i['severity']}] {i['title']}: {i['detail']}" for i in items) or "(none)"


def build_input(db: Session, user_text: str, passages: list[retrieval.Passage], triage_note: str = "") -> str:
    case = db.get(Case, 1)
    docs = db.query(Document).order_by(Document.doc_date.desc(), Document.id.desc()).limit(15).all()
    doc_list = "\n".join(f"- D{d.id}: {d.filename} ({d.doc_type}, {d.doc_date or 'date unknown'})" for d in docs) or "(none)"
    events = db.query(Event).order_by(Event.ts.desc()).limit(8).all()
    timeline = "\n".join(f"- {e.ts:%Y-%m-%d} {e.title}" for e in events) or "(none)"
    history = db.query(ChatMessage).order_by(ChatMessage.id.desc()).limit(HISTORY_TURNS + 1).all()[::-1]
    if history and history[-1].role == "user" and history[-1].content == user_text:
        history = history[:-1]  # the current message is appended separately
    convo = "\n".join(f"{'User' if m.role == 'user' else 'Assistant'}: {m.content[:1500]}" for m in history)
    parts = [
        f"CASE FILE (current values: the latest dated information)\n{case_summary(case)}",
        f"CASE HISTORY (dated; earlier values are superseded, never present them as current)\n{casefile.history_context(db)}",
        f"STRUCTURED PROGRESS AND READINESS (computed by the app from confirmed data; use these numbers as given)\n{readiness.context_block(db)}",
        f"OPEN POINTS THE APP HAS FLAGGED\n{_insight_lines(db)}",
        f"OPEN ADVISOR RECOMMENDATIONS (quoted from the records; cite with the [R#] tag)\n{recommendations.context_lines(db) or '(none recorded)'}",
        f"DAILY LIFE (self-reported by the patient or caregiver in the app; not verified, never a medical record)\n{wellness.context_lines(db) or '(nothing recorded yet)'}",
        f"DOCUMENTS ON FILE\n{doc_list}",
        f"RECENT TIMELINE\n{timeline}",
        f"DOCUMENT EXCERPTS\n{_passage_block(passages)}",
    ]
    if triage_note:
        parts.append(f"TRIAGE NOTE\n{triage_note}")
    if convo:
        parts.append(f"PREVIOUS CONVERSATION\n{convo}")
    parts.append(f"CURRENT USER MESSAGE\n{user_text}")
    return "\n\n".join(parts)


def _check_citations(answer: str, passages: list[retrieval.Passage]) -> tuple[str, list[dict]]:
    """Keep only citations that point at excerpts actually supplied; drop invented ones."""
    known = {(p.document_id, p.page): p for p in passages}
    known_docs = {p.document_id: p for p in passages}
    resolved: dict[tuple[int, int], dict] = {}

    def repl(m: re.Match[str]) -> str:
        valid: list[str] = []
        for tag in _TAG.finditer(m.group(1)):
            doc_id = int(tag.group(1))
            page = int(tag.group(2)) if tag.group(2) else None
            p = known.get((doc_id, page)) if page else known_docs.get(doc_id)
            if p is None:
                continue
            resolved[(p.document_id, p.page)] = {
                "document_id": p.document_id, "page": p.page, "filename": p.filename, "doc_date": p.doc_date,
            }
            valid.append(tag.group(0))
        return f"[{', '.join(valid)}]" if valid else ""

    return re.sub(r" {2,}", " ", _CITATION.sub(repl, answer)), list(resolved.values())


def answer(db: Session, user_text: str, role: str = "patient") -> Reply:
    settings = get_settings()
    started = time.monotonic()
    triage = safety.triage(user_text)
    flags: list[dict] = []
    error = ""
    lint_hits: list[str] = []
    passages: list[retrieval.Passage] = []

    db.add(ChatMessage(role="user", content=user_text))
    if triage.level:
        flags.append({"type": "triage", "level": triage.level, "reasons": [h.message for h in triage.hits]})
        db.add(Event(kind="alert", title=f"Red flag in chat: {', '.join(triage.flag_ids)}", detail=triage.level))
    db.commit()

    banner = safety.triage_message(triage, settings.emergency_number) if triage.level else ""
    if triage.level == safety.EMERGENCY:
        reply = Reply(banner, [], flags)
        _persist(db, reply, triage.flag_ids, [], [], started, "")
        return reply

    passages = retrieval.search(db, user_text) or retrieval.latest_per_document(db)
    system = f"{SYSTEM_PROMPT}\n{ROLE_NOTES.get(role, ROLE_NOTES['patient'])}"
    prompt_input = build_input(db, user_text, passages, banner)
    try:
        text = llm.chat(system, prompt_input)
        lint_hits = safety.lint(text)
        if lint_hits:
            retry = (
                f"{prompt_input}\n\nYour previous draft broke safety rules ({', '.join(lint_hits)}). Rewrite it "
                "without telling the user to start, stop, change or dose any treatment, without confirming a "
                "diagnosis and without promising outcomes; refer those decisions to the oncology team."
            )
            text = llm.chat(system, retry)
            lint_hits = safety.lint(text)
            if lint_hits:
                flags.append({"type": "safety", "rules": lint_hits})
                text = safety.SAFE_FALLBACK
        text, citations = _check_citations(text, passages)
    except llm.LLMError as exc:
        error = str(exc)
        text, citations = f"I couldn't get an answer from the local AI model: {error}", []
        flags.append({"type": "error", "message": error})

    content = f"{banner}\n\n---\n\n{text}" if banner else text
    reply = Reply(content, citations, flags)
    _persist(db, reply, triage.flag_ids, lint_hits, [f"D{p.document_id} p{p.page}" for p in passages], started, error)
    return reply


def _persist(db: Session, reply: Reply, triage_ids, lint_hits, retrieved, started: float, error: str) -> None:
    db.add(ChatMessage(role="assistant", content=reply.content, citations=reply.citations, flags=reply.flags))
    db.add(
        AgentRun(
            prompt_version=PROMPT_VERSION,
            model=get_settings().lm_model,
            triage=list(triage_ids),
            lint=list(lint_hits),
            retrieved=list(retrieved),
            latency_ms=int((time.monotonic() - started) * 1000),
            error=error,
        )
    )
    db.commit()


def _validated_events(raw_events, text: str, document: Document) -> tuple[list[dict], list[dict]]:
    """Keep only events whose quote really is in the document; an unseen date is dropped but the event is kept."""
    from app.services import scan_extract

    dates = scan_extract.find_dates(text) | ({document.doc_date} if document.doc_date else set())
    events, rejected = [], []
    for raw in raw_events or []:
        if not isinstance(raw, dict):
            continue
        title, quote, when = str(raw.get("title") or "").strip(), str(raw.get("quote") or ""), str(raw.get("date") or "").strip()
        if not title or not scan_extract.quote_supported(quote, text):
            rejected.append({"item": f"event {title[:60] or '?'}", "reason": "quote not found in the document"})
            continue
        if when and when not in dates:
            rejected.append({"item": f"date {when} for {title[:50]}", "reason": "date not found in the document; event kept without a date"})
            when = ""
        category = raw.get("category") if raw.get("category") in casefile.EVENT_CATEGORIES else "other"
        events.append({"date": when, "category": category, "title": title, "detail": str(raw.get("detail") or "").strip(), "quote": quote})
    return events, rejected


def extract_events(db: Session, document: Document) -> tuple[list[dict], list[dict]]:
    """Events only (lighter and faster than a full case-file extraction), verified against the document."""
    from app.services import scan_extract

    text = scan_extract.document_text(db, document)
    if not text.strip():
        raise llm.LLMError("This document has no readable text yet.")
    data = llm.chat_json(EVENTS_SYSTEM, f"DOCUMENT ({document.filename}, {document.doc_date or 'date unknown'}):\n{text[:12000]}")
    return _validated_events(data.get("events"), text, document)


def extract_case_fields(db: Session, document: Document) -> dict:
    """Propose dated Case File history from one document. Nothing is saved until the user confirms.

    Returns {"fields", "as_of", "events", "rejected"}. `as_of` is the document's date: values describe the
    situation then, and only become the current case file if nothing newer exists."""
    from app.services import scan_extract

    text = scan_extract.document_text(db, document)
    if not text.strip():
        raise llm.LLMError("This document has no readable text yet.")
    data = llm.chat_json(EXTRACT_SYSTEM, f"DOCUMENT ({document.filename}, {document.doc_date or 'date unknown'}):\n{text[:12000]}")
    raw_fields = data.get("fields") if isinstance(data.get("fields"), dict) else data  # tolerate the older flat shape
    fields = {k: str(raw_fields.get(k, "") or "").strip() for k in EXTRACT_KEYS}
    events, rejected = _validated_events(data.get("events"), text, document)
    return {"fields": fields, "as_of": document.doc_date or "", "events": events, "rejected": rejected}
