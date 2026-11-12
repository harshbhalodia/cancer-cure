"""Daily life alongside treatment: medicines, diet, routine, mind (manifestation), movement and support.

Everything here is *tracking*: what you intend to do, what you did, how you felt. The app never gives a dose or
treatment advice. Medicines come from your documents (quoted, shown as "suggested" until you confirm them) or from
you. Improvements are plain arithmetic over your own check-ins and ticks, so they can be trusted and explained.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CheckIn, Document, Habit, HabitLog, Setting
from app.services import llm, safety, scan_extract
from app.services.prompts import MEDS_SYSTEM

DOMAINS: dict[str, dict] = {
    "medication": {"label": "Medicines", "icon": "💊", "why": "Taken as your doctors prescribed. The app only helps you remember and record; it never changes a dose."},
    "diet": {"label": "Diet", "icon": "🥗", "why": "Steady nutrition and fluids help the body cope with treatment. Check any diet change, supplement or herbal product with your oncology team or dietitian first."},
    "routine": {"label": "Routine", "icon": "🗓️", "why": "A predictable day lowers stress and makes it easier to notice what changes."},
    "mind": {"label": "Mind & manifestation", "icon": "🌅", "why": "Intention, visualisation, breathing and gratitude support how you feel and cope. They support wellbeing; they are not a treatment for the cancer."},
    "movement": {"label": "Movement & rest", "icon": "🚶", "why": "Gentle activity and proper rest, at the level your care team says is right for now."},
    "support": {"label": "People & support", "icon": "🤝", "why": "Cancer is easier with company. Keep your caregiver and care team in the loop."},
}
WHEN = ("morning", "midday", "evening", "bedtime", "anytime")
STATUSES = ("suggested", "active", "paused", "dropped")

# Gentle, generic starting ideas. They are offered, never imposed, and the screen says to confirm with the care team.
STARTERS: list[dict] = [
    {"key": "protein", "domain": "diet", "title": "A protein food at every meal", "when": "anytime",
     "detail": "Egg, dal, curd, paneer, fish or chicken, as your diet allows. Protein helps the body repair."},
    {"key": "small-meals", "domain": "diet", "title": "Small, frequent meals if appetite is low", "when": "anytime",
     "detail": "Several small meals are often easier than three big ones. Soft, moist or blended food helps if chewing or swallowing is hard."},
    {"key": "fluids", "domain": "diet", "title": "Sip fluids steadily through the day", "when": "anytime",
     "detail": "Water, buttermilk or soups, unless your team has limited fluids."},
    {"key": "mouth-care", "domain": "diet", "title": "Gentle mouth care after meals", "when": "evening",
     "detail": "Rinse gently; use only the mouthwash your dental or oncology team recommended."},
    {"key": "same-times", "domain": "routine", "title": "Keep a regular wake-up and bedtime", "when": "bedtime",
     "detail": "A steady sleep rhythm helps energy, mood and healing."},
    {"key": "set-out-meds", "domain": "medication", "title": "Set out tomorrow's medicines", "when": "bedtime",
     "detail": "Check the list against your latest prescription so nothing is missed."},
    {"key": "med-list", "domain": "medication", "title": "Keep one up-to-date list of medicines and supplements", "when": "anytime",
     "detail": "Show it at every doctor and pharmacy visit."},
    {"key": "file-papers", "domain": "routine", "title": "Add today's papers or reports to the app", "when": "evening",
     "detail": "Drop new reports and advice here so the plan stays current."},
    {"key": "visit-questions", "domain": "support", "title": "Jot down a question for the next doctor visit", "when": "anytime",
     "detail": "Questions are easy to forget in the room."},
    {"key": "visualise", "domain": "mind", "title": "Visualise my recovery for 5 minutes", "when": "morning",
     "detail": "Picture the day you are working towards in detail: where you are, who is with you, how your body feels."},
    {"key": "breathing", "domain": "mind", "title": "Slow breathing for 5 minutes", "when": "evening",
     "detail": "Breathe in gently, breathe out a little longer. It calms the body and the mind."},
    {"key": "gratitude", "domain": "mind", "title": "Write one thing I am grateful for", "when": "bedtime",
     "detail": "Small, specific things count."},
    {"key": "calm-time", "domain": "mind", "title": "A prayer, meditation or something that calms me", "when": "anytime",
     "detail": "Whatever settles you."},
    {"key": "walk", "domain": "movement", "title": "A gentle walk", "when": "morning",
     "detail": "A few minutes at a comfortable pace, if your team says activity is fine for now."},
    {"key": "therapy-exercises", "domain": "movement", "title": "The exercises my therapist gave me", "when": "anytime",
     "detail": "Speech, swallowing, jaw or neck exercises, exactly as taught."},
    {"key": "rest", "domain": "movement", "title": "A rest break in the afternoon", "when": "midday",
     "detail": "Resting is part of recovery, not a lapse."},
    {"key": "talk", "domain": "support", "title": "Talk to someone I trust", "when": "evening",
     "detail": "A call, a visit or a message."},
    {"key": "joy", "domain": "support", "title": "One small thing I enjoy", "when": "anytime",
     "detail": "Music, a show, a hobby, time with family."},
]
GENTLE_SET = ("protein", "fluids", "walk", "breathing", "visualise", "gratitude", "talk")


def _day(value: str | None) -> str:
    if not value:
        return date.today().isoformat()
    return date.fromisoformat(value).isoformat()


# ------------------------------------------------------------------------------------ settings
def get_setting(db: Session, key: str) -> str:
    row = db.get(Setting, key)
    return row.value if row else ""


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value.strip()[:1000]))
    else:
        row.value = value.strip()[:1000]
    db.commit()


# ------------------------------------------------------------------------------------ habits
def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


_MED_PREFIX = {"tab", "tablet", "cap", "capsule", "syp", "syrup", "inj", "injection", "oint", "ointment", "gel"}


def _med_key(name: str) -> str:
    words = [w for w in re.findall(r"[a-z]+", name.lower()) if w not in _MED_PREFIX]
    return words[0] if words else _norm(name)


def add_habit(db: Session, *, domain: str, title: str, detail: str = "", when: str = "anytime", source: str = "you",
              status: str = "active", dose: str = "", prescriber: str = "", document_id: int | None = None,
              quote: str = "") -> Habit | None:
    title = (title or "").strip()[:200]
    if domain not in DOMAINS or not title:
        return None
    for h in db.query(Habit).filter(Habit.domain == domain, Habit.status != "dropped"):
        same = _med_key(h.title) == _med_key(title) if domain == "medication" else _norm(h.title) == _norm(title)
        if same:
            return None
    habit = Habit(domain=domain, title=title, detail=(detail or "").strip(), when=when if when in WHEN else "anytime",
                  source=source, status=status if status in STATUSES else "active", dose=(dose or "").strip()[:300],
                  prescriber=(prescriber or "").strip()[:200], document_id=document_id, quote=quote)
    db.add(habit)
    db.flush()
    return habit


def add_starters(db: Session, keys: list[str]) -> int:
    added = 0
    for s in STARTERS:
        if s["key"] in keys and add_habit(db, domain=s["domain"], title=s["title"], detail=s["detail"], when=s["when"], source="starter"):
            added += 1
    db.commit()
    return added


def library(db: Session) -> list[dict]:
    have = {(h.domain, _norm(h.title)) for h in db.query(Habit).filter(Habit.status != "dropped")}
    return [{**s, "added": (s["domain"], _norm(s["title"])) in have} for s in STARTERS]


def update_habit(db: Session, habit_id: int, patch: dict) -> Habit | None:
    h = db.get(Habit, habit_id)
    if h is None:
        return None
    for key in ("title", "detail", "dose", "prescriber"):
        if patch.get(key) is not None:
            setattr(h, key, str(patch[key]).strip())
    if patch.get("when") in WHEN:
        h.when = patch["when"]
    if patch.get("status") in STATUSES:
        h.status = patch["status"]
    db.commit()
    return h


def set_done(db: Session, habit_id: int, day: str, done: bool) -> bool:
    day = _day(day)
    if db.get(Habit, habit_id) is None:
        return False
    row = db.query(HabitLog).filter_by(habit_id=habit_id, day=day).first()
    if done and row is None:
        db.add(HabitLog(habit_id=habit_id, day=day))
    elif not done and row is not None:
        db.delete(row)
    db.commit()
    return True


def _logs(db: Session) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for habit_id, day in db.query(HabitLog.habit_id, HabitLog.day):
        out.setdefault(habit_id, set()).add(day)
    return out


def _streak(days: set[str], today: date) -> int:
    cursor = today if today.isoformat() in days else today - timedelta(days=1)
    n = 0
    while cursor.isoformat() in days:
        n += 1
        cursor -= timedelta(days=1)
    return n


# ------------------------------------------------------------------------------------ check-ins
SCALES = {"energy": (1, 5), "mood": (1, 5), "appetite": (1, 5), "pain": (0, 10), "sleep_hours": (0, 24), "weight_kg": (20, 300)}
TEXTS = ("symptoms", "note", "intention", "gratitude")


def checkin_dict(row: CheckIn | None) -> dict | None:
    if row is None:
        return None
    return {k: getattr(row, k) for k in ("day", *SCALES, *TEXTS)}


def get_checkin(db: Session, day: str) -> dict | None:
    return checkin_dict(db.query(CheckIn).filter_by(day=_day(day)).first())


def save_checkin(db: Session, day: str, fields: dict) -> dict:
    """Partial update: only the fields given are changed. `null` clears a number. Returns the row and any safety alert."""
    day = _day(day)
    row = db.query(CheckIn).filter_by(day=day).first()
    if row is None:
        row = CheckIn(day=day)
        db.add(row)
    for key, (lo, hi) in SCALES.items():
        if key in fields:
            v = fields[key]
            if v is None or v == "":
                setattr(row, key, None)
            else:
                num = float(v)
                if not lo <= num <= hi:
                    raise ValueError(f"{key} must be between {lo} and {hi}.")
                setattr(row, key, num if key in ("sleep_hours", "weight_kg") else int(round(num)))
    for key in TEXTS:
        if key in fields:
            setattr(row, key, str(fields[key] or "").strip()[:1000])
    db.commit()
    alert = None
    triage = safety.triage(f"{row.symptoms} {row.note}")
    emergency = get_settings().emergency_number
    if triage.level:
        reasons = "; ".join(h.message for h in triage.hits)
        if triage.level == safety.EMERGENCY:
            text = (f"**This may be an emergency ({reasons}).** Please call your local emergency number ({emergency}) or go to the "
                    "nearest emergency department now, tell someone nearby, and mention the cancer diagnosis and current treatment.")
        else:
            text = (f"**Please contact your oncology team today ({reasons}).** During cancer treatment this can need same-day review. "
                    f"If they are unreachable or it gets worse, go to the nearest emergency department ({emergency}).")
        alert = {"level": triage.level, "message": text}
    elif row.pain is not None and row.pain >= 8:
        alert = {"level": "urgent", "message": f"**Pain this high is worth a call to your oncology team today.** If it is unbearable or you feel unsafe, go to the nearest emergency department ({emergency})."}
    return {"checkin": checkin_dict(row), "alert": alert}


# ------------------------------------------------------------------------------------ today
def _habit_dict(h: Habit, done: set[str], today: date, filenames: dict[int, str]) -> dict:
    return {
        "id": h.id, "domain": h.domain, "title": h.title, "detail": h.detail, "when": h.when, "dose": h.dose,
        "prescriber": h.prescriber, "source": h.source, "status": h.status, "quote": h.quote, "document_id": h.document_id,
        "filename": filenames.get(h.document_id, ""), "done": today.isoformat() in done, "streak": _streak(done, today),
        "week": [(today - timedelta(days=6 - i)).isoformat() in done for i in range(7)],
    }


def today_view(db: Session, day: str | None = None) -> dict:
    day = _day(day)
    today = date.fromisoformat(day)
    logs = _logs(db)
    filenames = {d.id: d.filename for d in db.query(Document)}
    rows = db.query(Habit).filter(Habit.status.in_(("active", "suggested"))).order_by(Habit.id).all()
    habits = [_habit_dict(h, logs.get(h.id, set()), today, filenames) for h in rows]
    active = [h for h in habits if h["status"] == "active"]
    order = {w: i for i, w in enumerate(WHEN)}
    active.sort(key=lambda h: (order.get(h["when"], 9), h["id"]))
    return {
        "day": day, "domains": [{"id": k, **v} for k, v in DOMAINS.items()], "when": list(WHEN),
        "habits": active, "suggested_medicines": [h for h in habits if h["status"] == "suggested"],
        "done": sum(h["done"] for h in active), "total": len(active),
        "checkin": get_checkin(db, day), "vision": get_setting(db, "vision"),
        "checkin_streak": _checkin_streak(db, today),
    }


def _checkin_streak(db: Session, today: date) -> int:
    days = {d for (d,) in db.query(CheckIn.day)}
    cursor = today if today.isoformat() in days else today - timedelta(days=1)
    n = 0
    while cursor.isoformat() in days:
        n += 1
        cursor -= timedelta(days=1)
    return n


# ------------------------------------------------------------------------------------ improvements
METRICS = {
    "energy": {"label": "Energy", "better": "up", "unit": "/5", "step": 0.3},
    "mood": {"label": "Mood", "better": "up", "unit": "/5", "step": 0.3},
    "appetite": {"label": "Appetite", "better": "up", "unit": "/5", "step": 0.3},
    "pain": {"label": "Pain", "better": "down", "unit": "/10", "step": 0.5},
    "sleep_hours": {"label": "Sleep", "better": "up", "unit": " h", "step": 0.5},
    "weight_kg": {"label": "Weight", "better": None, "unit": " kg", "step": 0.5},
}


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _adherence(habits: list[Habit], logs: dict[int, set[str]], start: date, end: date) -> float | None:
    expected = done = 0
    for h in habits:
        created = h.created_at.date()
        for i in range((end - start).days + 1):
            d = start + timedelta(days=i)
            if d < created or d > end:
                continue
            expected += 1
            done += d.isoformat() in logs.get(h.id, set())
    return round(done / expected, 2) if expected else None


def trends(db: Session, day: str | None = None) -> dict:
    today = date.fromisoformat(_day(day))
    this_start, prev_start = today - timedelta(days=6), today - timedelta(days=13)
    rows = {r.day: r for r in db.query(CheckIn).filter(CheckIn.day >= prev_start.isoformat(), CheckIn.day <= today.isoformat())}
    metrics = []
    for key, meta in METRICS.items():
        series = [{"day": d, "value": getattr(r, key)} for d, r in sorted(rows.items()) if getattr(r, key) is not None]
        now = [s["value"] for s in series if s["day"] >= this_start.isoformat()]
        before = [s["value"] for s in series if s["day"] < this_start.isoformat()]
        a, b = _avg(now), _avg(before)
        verdict = None
        if a is not None and b is not None and len(now) >= 2 and len(before) >= 2:
            delta = round(a - b, 1)
            if abs(delta) < meta["step"]:
                verdict = "steady"
            elif meta["better"] is None:
                verdict = "up" if delta > 0 else "down"
            else:
                verdict = "better" if (delta > 0) == (meta["better"] == "up") else "worse"
        metrics.append({"key": key, "label": meta["label"], "unit": meta["unit"], "series": series, "this_week": a, "last_week": b,
                        "n_this": len(now), "n_last": len(before), "verdict": verdict, "lower_is_better": meta["better"] == "down"})
    logs = _logs(db)
    adherence = []
    for dom, meta in DOMAINS.items():
        hs = db.query(Habit).filter_by(domain=dom, status="active").all()
        if not hs:
            continue
        adherence.append({"domain": dom, "label": meta["label"], "icon": meta["icon"], "habits": len(hs),
                          "this_week": _adherence(hs, logs, this_start, today), "last_week": _adherence(hs, logs, prev_start, this_start - timedelta(days=1))})
    return {"day": today.isoformat(), "metrics": metrics, "adherence": adherence, "headlines": _headlines(metrics, adherence),
            "checkin_days": db.query(CheckIn).count(), "checkin_streak": _checkin_streak(db, today)}


def _headlines(metrics: list[dict], adherence: list[dict]) -> list[dict]:
    out = []
    word = {"better": "better", "worse": "lower", "steady": "about the same", "up": "up", "down": "down"}
    for m in metrics:
        if m["verdict"]:
            tone = {"better": "good", "worse": "watch", "steady": "calm"}.get(m["verdict"], "calm")
            if m["verdict"] == "worse" and m["key"] == "pain":
                word_ = "higher"
            else:
                word_ = word[m["verdict"]]
            out.append({"tone": tone, "text": f"{m['label']} averaged {m['this_week']}{m['unit']} this week vs {m['last_week']}{m['unit']} the week before — {word_}."})
    for a in adherence:
        if a["this_week"] is not None:
            pct = round(a["this_week"] * 100)
            tail = "" if a["last_week"] is None else f" (was {round(a['last_week'] * 100)}%)"
            out.append({"tone": "good" if pct >= 70 else "calm", "text": f"{a['label']}: {pct}% of planned days done this week{tail}."})
    return out


# ------------------------------------------------------------------------------------ facts for advisors and chat
def strategy_facts(db: Session) -> str:
    lines = []
    vision = get_setting(db, "vision")
    if vision:
        lines.append(f"Recovery vision, in the patient's own words: {vision}")
    for dom, meta in DOMAINS.items():
        hs = db.query(Habit).filter_by(domain=dom, status="active").all()
        if hs:
            lines.append(f"{meta['label']} already in the daily plan:")
            for h in hs:
                extra = f" — {h.dose}" if h.dose else ""
                lines.append(f"- {h.title}{extra} ({h.when})")
        else:
            lines.append(f"{meta['label']}: nothing in the daily plan yet.")
    t = trends(db)
    if t["headlines"]:
        lines.append("Last two weeks (the patient's own check-ins):")
        lines += [f"- {h['text']}" for h in t["headlines"]]
    else:
        lines.append(f"Check-ins so far: {t['checkin_days']} day(s); not enough yet to compare weeks.")
    return "\n".join(lines)


def context_lines(db: Session) -> str:
    meds = db.query(Habit).filter_by(domain="medication", status="active").all()
    lines = [f"- Medicine the patient lists: {m.title}" + (f" ({m.dose})" if m.dose else "") for m in meds]
    for r in db.query(CheckIn).order_by(CheckIn.day.desc()).limit(3):
        bits = [f"{k} {getattr(r, k)}" for k in SCALES if getattr(r, k) is not None]
        text = "; ".join(x for x in (r.symptoms, r.note) if x)
        lines.append(f"- Check-in {r.day}: {', '.join(bits) or 'no scores'}" + (f"; said: {text}" if text else ""))
    return "\n".join(lines)


def fingerprint_part(db: Session) -> str:
    habits = db.query(Habit).filter(Habit.status != "dropped").count()
    last = db.query(Habit.id).order_by(Habit.id.desc()).first()
    return f"habits {habits}:{last[0] if last else 0}|checkins {db.query(CheckIn).count() // 7}"


# ------------------------------------------------------------------------------------ medicines from documents
_MED_HINT = re.compile(r"\b(tab\.?|tablets?|cap\.?|capsules?|syp\.?|syrup|inj\.?|injections?|mg|mcg|ml|ointment|mouth ?wash|rx|bd|tds|od|sos|dose)\b", re.I)


def worth_reading(text: str, doc_type: str) -> bool:
    return doc_type != "imaging" and bool(_MED_HINT.search(text or ""))


def extract_medicines(db: Session, doc: Document) -> tuple[list[dict], list[dict]]:
    text = scan_extract.document_text(db, doc)
    if not text.strip():
        raise llm.LLMError("This document has no readable text yet.")
    data = llm.chat_json(MEDS_SYSTEM, f"DOCUMENT ({doc.filename}, {doc.doc_date or 'date unknown'}):\n{text[:12000]}")
    kept, rejected = [], []
    for raw in data.get("medicines") or []:
        if not isinstance(raw, dict):
            continue
        name, quote = str(raw.get("name") or "").strip(), str(raw.get("quote") or "")
        if not name:
            continue
        words = [w for w in re.findall(r"[a-z]{4,}", name.lower()) if w not in _MED_PREFIX]
        if not scan_extract.quote_supported(quote, text) or not any(w in quote.lower() for w in words):
            rejected.append({"item": name[:60], "reason": "quote not found in the document, or it does not contain the name"})
            continue
        kept.append({"name": name, "dose": str(raw.get("dose") or "").strip(), "purpose": str(raw.get("purpose") or "").strip(),
                     "prescriber": str(raw.get("prescriber") or "").strip(), "quote": quote})
    return kept, rejected


def add_found_medicines(db: Session, doc: Document, found: list[dict]) -> int:
    added = 0
    for m in found:
        detail = f"For: {m['purpose']}" if m["purpose"] else ""
        if add_habit(db, domain="medication", title=m["name"], detail=detail, dose=m["dose"], prescriber=m["prescriber"],
                     source="document", status="suggested", document_id=doc.id, quote=m["quote"]):
            added += 1
    return added
