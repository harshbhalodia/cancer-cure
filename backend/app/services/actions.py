from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import CareAction, Event, Habit, Reading, Recommendation, Signal, Trial, utcnow
from app.services import casefile, priorities, trials

ACTIVE = {"open", "contacted", "awaiting_reply"}
PRIORITY = {"urgent": 0, "high": 1, "routine": 2}


def as_dict(row: CareAction) -> dict:
    return {**{k: getattr(row, k) for k in (
        "id", "title", "why", "owner", "due_date", "priority", "status", "source_key", "evidence", "answer", "answer_source", "history"
    )}, "overdue": bool(row.due_date and row.due_date < date.today().isoformat() and row.status in ACTIVE),
        "updated_at": row.updated_at.isoformat()}


def suggestions(db: Session) -> list[dict]:
    existing = {r.source_key for r in db.query(CareAction) if r.source_key}
    out: list[dict] = []
    for signal in db.query(Signal).filter(Signal.status != "resolved", Signal.level.in_(("urgent", "emergency"))):
        out.append({"source_key": f"signal:{signal.id}", "title": f"Follow up: {signal.title}", "why": signal.why,
                    "priority": "urgent", "evidence": {"kind": "app_alert", "signal_id": signal.id, "text": signal.why}})
    for rec in db.query(Recommendation).filter_by(status="open").order_by(Recommendation.id.desc()):
        out.append({"source_key": f"recommendation:{rec.id}", "title": rec.text[:300], "why": "Confirm and follow up with the care team; this task is not a medical order.",
                    "priority": "urgent" if rec.urgency == "urgent" else "high" if rec.urgency == "high" else "routine",
                    "evidence": {"kind": rec.source, "recommendation_id": rec.id, "document_id": rec.document_id, "quote": rec.quote,
                                 "advisor": rec.advisor, "date": rec.rec_date, "text": rec.text}})
    for trial in db.query(Trial).order_by(Trial.id):
        for issue in trials.assess(db, trial)["key_issues"]:
            out.append({"source_key": f"trial:{trial.id}:{issue['key']}", "title": f"{trial.nct_id}: clarify {issue['key']}",
                        "why": issue["ask"] or issue["text"], "priority": "high",
                        "evidence": {"kind": "trial_question", "trial_id": trial.id, "nct_id": trial.nct_id,
                                     "criterion": issue["criterion"], "text": issue["text"]}})
    return sorted((s for s in out if s["source_key"] not in existing), key=lambda s: PRIORITY[s["priority"]])


def view(db: Session) -> dict:
    rows = [as_dict(r) for r in db.query(CareAction)]
    rows.sort(key=lambda r: (r["status"] not in ACTIVE, PRIORITY[r["priority"]], not r["overdue"], r["due_date"] or "9999", -r["id"]))
    return {"items": rows, "focus": [r for r in rows if r["status"] in ACTIVE][:3], "suggestions": suggestions(db),
            "note": "Follow-up tasks do not acknowledge safety alerts or change treatment. Urgent symptoms need care now, not a task deadline."}


def record_change(db: Session, row: CareAction, changes: dict, note: str = "") -> None:
    row.history = [*(row.history or []), {"at": utcnow().isoformat(), "changes": changes, "note": note}]
    db.add(Event(kind="action", title=f"Follow-up: {row.title}", detail=f"Status: {row.status}. {note}", ref_type="care_action", ref_id=row.id))


def create(db: Session, fields: dict) -> CareAction:
    source_key = fields.pop("source_key", None)
    if source_key:
        if db.query(CareAction).filter_by(source_key=source_key).first():
            raise ValueError("This item is already tracked.")
        suggestion = next((s for s in suggestions(db) if s["source_key"] == source_key), None)
        if suggestion is None:
            raise ValueError("This suggestion is no longer available. Refresh the action list.")
        fields.update({k: suggestion[k] for k in ("title", "why", "priority", "evidence")})
    if not fields.get("title"):
        raise ValueError("Add a title or choose a suggested follow-up.")
    row = CareAction(source_key=source_key, **fields)
    db.add(row)
    db.flush()
    record_change(db, row, {"status": "open"}, "Task added by you.")
    db.commit()
    return row


def update(db: Session, row: CareAction, fields: dict) -> None:
    status = fields.get("status", row.status)
    answer = fields.get("answer", row.answer)
    if status == "resolved" and not answer.strip():
        raise ValueError("Record the answer or resolution before closing this follow-up.")
    changed = {k: v for k, v in fields.items() if getattr(row, k) != v}
    for key, value in changed.items():
        setattr(row, key, value)
    if changed:
        record_change(db, row, changed)
        db.commit()


def visit_text(db: Session) -> str:
    values, _ = casefile.derive(db)
    lines = ["Patient visit preparation", "Review before sharing. No records are sent automatically.",
             "Patient-entered facts and answers are not independently verified.", ""]
    for key in ("diagnosis", "current_treatment", "allergies"):
        lines.append(f"{casefile.LABELS[key]}: {values.get(key) or 'unknown'}")
    scan = priorities.latest_scan(db)
    lines += ["", f"Latest scan: {scan.modality} {scan.scan_date}; report says {scan.reported_label or 'no conclusion recorded'}" if scan else "Latest scan: unknown",
              "", "Active medicines (user-confirmed, verify against prescription):"]
    meds = db.query(Habit).filter_by(domain="medication", status="active").all()
    lines += [f"- {m.title}: {m.dose or 'dose not recorded'}" for m in meds] or ["- Unknown"]
    recent = db.query(Reading).order_by(Reading.ts.desc()).limit(7).all()
    lines += ["", "Recent self-reported check-ins (not a cancer response measurement):"]
    lines += [f"- {r.day}: pain {r.pain if r.pain is not None else 'unknown'}; appetite {r.appetite if r.appetite is not None else 'unknown'}; symptoms {', '.join(r.flags or []) or 'not entered'}; {r.note}" for r in recent] or ["- None entered"]
    lines += ["", "Follow-up questions and recorded answers:"]
    for row in view(db)["items"]:
        lines.append(f"- [{row['status']}] {row['title']} | owner {row['owner']} | due {row['due_date'] or 'not set'}")
        if row["why"]:
            lines.append(f"  Question/context: {row['why']}")
        if row["answer"]:
            lines.append(f"  Answer ({row['answer_source']}; entered by user, unverified): {row['answer']}")
    return "\n".join(lines)
