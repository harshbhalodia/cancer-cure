"""The consultation checklist: what to ask and tell the doctor today, and a place to record what you were told.

Sections come from the latest scan and your journey by plain code (no model), in the order that matters:
the urgent finding, the active lesion, the lymph node, previous treatment, then the overall plan. The questions
are for the treating team; none of them is advice. During the visit you tick what you asked and type the answers.
Saving the visit adds a dated consultation to the journey and turns each line of advice you wrote down into a
tracked recommendation.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CheckIn, ClinicalEvent, Habit, Visit
from app.services import casefile, priorities, recommendations, wellness

TREATMENT_CATEGORIES = ("surgery", "radiotherapy", "chemotherapy", "immunotherapy")


def _key(section: str, text: str) -> str:
    return f"{section}.{hashlib.md5(text.encode()).hexdigest()[:8]}"


def _section(sid: str, title: str, priority: str, context: list[str], questions: list[str]) -> dict:
    return {"id": sid, "title": title, "priority": priority, "context": context,
            "questions": [{"key": _key(sid, q), "text": q} for q in questions]}


def sections(db: Session) -> list[dict]:
    out: list[dict] = []
    ts = {t["id"]: t for t in priorities.tracks(db)}
    scan = priorities.latest_scan(db)

    if "vessel" in ts:
        t = ts["vessel"]
        out.append(_section("vessel", "Urgent — blood clot in the neck vein", "urgent", [t["title"]] + t["facts"], t["asks"]))
    if "residual" in ts:
        t = ts["residual"]
        out.append(_section("residual", "Tongue lesion that is still active", "high", t["facts"], t["asks"]))

    if scan is not None:
        nodes = [l for l in priorities._lesions(scan) if re.search(r"node|nodal|lymph", f"{l['label']} {l['site']}", re.I)]
        node_findings = [f for f in scan.findings if f.category == "nodal" and f.certainty != "absent"]
        if nodes or node_findings:
            ctx = []
            for n in nodes:
                move = f"{priorities._fmt_mm(n['prior'])} → {priorities._fmt_mm(n['now'])}" if n["prior"] is not None else priorities._fmt_mm(n["now"])
                ctx.append(f"{n['label']}: {move}" + (f", SUVmax {n['suv']:g}" if n["suv"] is not None else "") + ".")
            ctx += [f"The report says: “{f.text}”." for f in node_findings[:1]]
            qs = ["Is this lymph node still metastatic disease?", "Does it need a biopsy or further investigation?"]
            if db.query(ClinicalEvent).filter(ClinicalEvent.category == "surgery").count():
                qs.append("Does the earlier neck surgery affect how the current findings should be read?")
            out.append(_section("node", "Neck lymph node", "high", ctx, qs))

    events = db.query(ClinicalEvent).filter(ClinicalEvent.category.in_(TREATMENT_CATEGORIES)).all()
    done_kinds = sorted({e.category for e in events if e.event_date and e.event_date <= date.today().isoformat()})
    pending = [r for r in recommendations.listing(db) if r["status"] == "open" and r["nature"] == "verify" and r["category"] in TREATMENT_CATEGORIES]
    if done_kinds or pending:
        kinds = ", ".join(done_kinds[:-1]) + (" and " if len(done_kinds) > 1 else "") + done_kinds[-1] if done_kinds else ""
        ctx = [f"Journey so far: {kinds}."] if done_kinds else []
        qs = [f"Was this planned treatment actually carried out? “{r['text']}” ({r['advisor'] or 'advisor'}, {r['rec_date']})" for r in pending[:3]]
        qs.append("Has the cancer responded adequately to the treatment so far?" if not done_kinds else f"Has the cancer responded adequately to the earlier {kinds}?")
        qs.append("Should further surgery, immunotherapy or another treatment be considered?")
        out.append(_section("history", "Previous treatment and surgery", "high", ctx, qs))

    plan_qs = [
        "Can the surgical, medical and radiation oncologists and the radiologist review this together (a multidisciplinary or tumour board review), before any surgical decision is made?",
        "What is the recommended next step, and how urgently should it happen?",
        "When should the next scan or follow-up assessment take place?",
        "What is the treatment objective now: complete disease control, further reduction, or managing residual disease?",
    ]
    if scan is not None and scan.comparator_date:
        plan_qs.append(f"Can the {scan.scan_date} {scan.modality or 'scan'} be compared with the actual earlier post-operative and treatment records, not only with the {scan.comparator_modality or 'earlier study'} of {scan.comparator_date}?")
    if ts or scan is not None:
        out.append(_section("plan", "Overall treatment plan", "high", ([f"Report conclusion: {scan.reported_label}."] if scan is not None and scan.reported_label else []), plan_qs))
    return out


def mention(db: Session) -> list[dict]:
    """Things to tell the doctor, each with what the app already knows so you don't have to remember."""
    today = date.today()
    ci_rows = db.query(CheckIn).order_by(CheckIn.day.desc()).limit(14).all()
    latest = ci_rows[0] if ci_rows else None
    weights = [(r.day, r.weight_kg) for r in reversed(ci_rows) if r.weight_kg is not None]
    appetite = [r.appetite for r in ci_rows[:7] if r.appetite is not None]
    meds = db.query(Habit).filter_by(domain="medication", status="active").all()
    items = [
        {"id": "neck", "text": "Any neck swelling, pain, redness or tenderness",
         "note": next((f"You noted on {r.day}: {r.symptoms}" for r in ci_rows if re.search(r"neck", f"{r.symptoms} {r.note}", re.I)), "")},
        {"id": "tongue", "text": "Any change in tongue swelling or pain",
         "note": f"Pain you recorded on {latest.day}: {latest.pain}/10." if latest and latest.pain is not None else ""},
        {"id": "eating", "text": "Difficulty swallowing, speaking or eating",
         "note": f"Appetite over the last check-ins: average {sum(appetite) / len(appetite):.1f}/5." if appetite else ""},
        {"id": "weight", "text": "Any weight loss or reduced food intake",
         "note": f"Weight recorded: {weights[0][1]:g} kg on {weights[0][0]} → {weights[-1][1]:g} kg on {weights[-1][0]}." if len(weights) >= 2 else (f"Last weight recorded: {weights[0][1]:g} kg." if weights else "")},
        {"id": "meds", "text": "All current medicines, especially blood thinners and cancer medicines",
         "note": ("In your daily plan: " + "; ".join(f"{m.title}" + (f" ({m.dose})" if m.dose else "") for m in meds) + ".") if meds else "None confirmed in the app yet. Bring the strips or the prescription."},
    ]
    return items


def leave_with(db: Session) -> list[str]:
    ts = {t["id"] for t in priorities.tracks(db)}
    out = []
    if "vessel" in ts:
        out.append("What is the immediate plan for the neck vein thrombosis?")
    if "residual" in ts:
        out.append("How will the doctors confirm whether the tongue lesion is still active cancer?")
    if ts:
        out.append("What is the next treatment, and when will it start?")
    return out


def emergency_line() -> str:
    em = get_settings().emergency_number
    return f"Sudden breathlessness, chest pain, coughing blood, fainting or new neurological symptoms: seek emergency care ({em}) instead of waiting for the appointment."


# ------------------------------------------------------------------------------------ the visit record
def get_visit(db: Session, day: str | None = None) -> Visit:
    day = wellness._day(day)
    v = db.query(Visit).filter_by(day=day).first()
    if v is None:
        v = Visit(day=day, answers={}, advice="")
        db.add(v)
        db.commit()
    return v


def set_item(db: Session, key: str, asked: bool | None, answer: str | None) -> Visit:
    v = get_visit(db)
    answers = dict(v.answers or {})
    cur = dict(answers.get(key) or {"asked": False, "answer": ""})
    if asked is not None:
        cur["asked"] = bool(asked)
    if answer is not None:
        cur["answer"] = answer.strip()[:2000]
        if cur["answer"]:
            cur["asked"] = True
    answers[key] = cur
    v.answers = answers
    db.commit()
    return v


def set_advice(db: Session, advice: str) -> Visit:
    v = get_visit(db)
    v.advice = advice.strip()[:4000]
    db.commit()
    return v


_CATS = [
    (r"biops", "biopsy"), (r"\b(mri|ct|pet|scan|ultrasound|doppler|x-?ray|imaging)\b", "imaging"),
    (r"surg|operat|dissection|resection", "surgery"), (r"radiother|radiation|\brt\b", "radiotherapy"),
    (r"chemo", "chemotherapy"), (r"immuno", "immunotherapy"), (r"refer|opinion|tumou?r board|multidisciplin", "referral"),
    (r"blood test|cbc|lft|kft|culture|marker|test\b", "test"), (r"review|follow|after \d|next visit|come back", "follow_up"),
]


def _category(line: str) -> str:
    low = line.lower()
    return next((c for pattern, c in _CATS if re.search(pattern, low)), "other")


def _summary(db: Session, v: Visit) -> str:
    texts = {q["key"]: q["text"] for s in sections(db) for q in s["questions"]}
    lines = []
    for key, a in (v.answers or {}).items():
        if a.get("answer"):
            lines.append(f"Q: {texts.get(key, 'Question')}\nA: {a['answer']}")
    if v.advice:
        lines.append("Advice noted:\n" + v.advice)
    return "\n\n".join(lines)


def finish(db: Session, day: str | None = None) -> dict:
    """Record the visit: a dated consultation in the journey, and each advice line as a tracked recommendation."""
    v = get_visit(db, day)
    detail = _summary(db, v)
    if not detail:
        raise ValueError("Write at least one answer or piece of advice first.")
    title = "Oncology consultation: questions and answers recorded"
    ev = db.get(ClinicalEvent, v.event_id) if v.event_id else None
    if ev is None:
        ev = casefile.add_event(db, v.day, "consultation", title, detail, source="you")
    else:
        ev.detail = detail
    added = 0
    for line in [l.strip(" -•\t") for l in v.advice.splitlines() if l.strip(" -•\t")]:
        if recommendations.add(db, text=line, category=_category(line), advisor=f"Doctor visit {v.day}", rec_date=v.day, certainty="advised", source="you"):
            added += 1
    v.status, v.event_id = "saved", ev.id if ev else None
    db.commit()
    return {"saved": True, "recommendations": added, "event": bool(ev)}


def history(db: Session) -> list[dict]:
    rows = db.query(Visit).filter(Visit.status == "saved").order_by(Visit.day.desc()).limit(10).all()
    return [{"day": v.day, "answered": sum(1 for a in (v.answers or {}).values() if a.get("answer")), "advice": v.advice} for v in rows]


def view(db: Session) -> dict:
    v = get_visit(db)
    return {
        "day": v.day, "status": v.status, "sections": sections(db), "mention": mention(db), "leave_with": leave_with(db),
        "emergency": emergency_line(), "answers": v.answers or {}, "advice": v.advice, "history": history(db),
    }


def checklist_text(db: Session) -> str:
    """The checklist as plain text for printing or sending."""
    lines = [f"Questions for the doctor — {date.today().isoformat()}", ""]
    for n, s in enumerate(sections(db), start=1):
        lines.append(f"{n}. {s['title']}")
        lines += [f"   {c}" for c in s["context"]]
        lines += [f"   [ ] {q['text']}" for q in s["questions"]]
        lines.append("")
    lines.append("Tell the doctor:")
    lines += [f"   [ ] {m['text']}" + (f" — {m['note']}" if m["note"] else "") for m in mention(db)]
    lw = leave_with(db)
    if lw:
        lines += ["", "Do not leave without clarity on:"] + [f"   {i}. {t}" for i, t in enumerate(lw, start=1)]
    lines += ["", emergency_line()]
    return "\n".join(lines)
