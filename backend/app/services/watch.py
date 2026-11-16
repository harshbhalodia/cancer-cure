"""The watch: log as often as you like, and the app compares each log with your own baseline, finds alarming and
recovering signs across symptoms, vitals, medicines, diet, routine, mind and reports, and says what to check or do
right now.

Everything here is plain, readable rules, not a hidden model, so every alert can say exactly why it fired. The
"predictions" are simple straight-line trends over your own recent days. The steps are escalation and checking
(call the team, recheck, log again), never treatment or doses. The thresholds below are conservative starting
points that the treating oncologist should review.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CheckIn, Habit, HabitLog, Reading, Recommendation, Scan, Signal
from app.services import safety, wellness

FLAGS: dict[str, dict] = {
    "neck_swelling": {"label": "Neck swollen, painful or red", "level": "urgent"},
    "breathless": {"label": "Short of breath", "level": "emergency"},
    "chest_pain": {"label": "Chest pain or tightness", "level": "emergency"},
    "coughing_blood": {"label": "Coughing blood", "level": "emergency"},
    "faint": {"label": "Fainting or very dizzy", "level": "emergency"},
    "confusion": {"label": "New confusion, weakness or slurred speech", "level": "emergency"},
    "bleeding": {"label": "Bleeding (mouth, wound, stool, urine)", "level": "urgent"},
    "fever_chills": {"label": "Fever, chills or shivering", "level": "urgent"},
    "vomiting": {"label": "Vomiting", "level": "watch"},
    "swallow_trouble": {"label": "Trouble swallowing", "level": "watch"},
    "new_lump": {"label": "New lump, sore or ulcer", "level": "urgent"},
    "leg_swelling": {"label": "Swollen, painful arm or leg", "level": "urgent"},
}
RANK = {"info": 0, "recovering": 1, "watch": 2, "urgent": 3, "emergency": 4}
RANGES = {"energy": (1, 5), "mood": (1, 5), "appetite": (1, 5), "pain": (0, 10), "temp_c": (30, 45), "pulse": (20, 250),
          "spo2": (50, 100), "bp_sys": (50, 260), "bp_dia": (30, 160), "weight_kg": (20, 300)}
INTS = ("energy", "mood", "appetite", "pain", "pulse", "spo2", "bp_sys", "bp_dia")

# thresholds: conservative starting points for the oncologist to review
FEVER_C = 38.0
SPO2_EMERGENCY, SPO2_URGENT = 92, 94
PULSE_HIGH, PULSE_LOW = 120, 45
BP_SYS_LOW, BP_SYS_HIGH = 90, 180
PAIN_URGENT = 8
ACUTE_HOURS = 8
WEIGHT_LOSS_WATCH_7D, WEIGHT_LOSS_URGENT_30D = 2.0, 5.0
MED_WINDOW_END = {"morning": (12, 0), "midday": (16, 0), "evening": (21, 0), "bedtime": (23, 30), "anytime": (20, 0)}
SELF_HARM = re.compile(r"\b(suicid\w*|end my life|kill myself|no point (in )?living|want to die|hopeless)\b", re.I)


def _now() -> datetime:
    return datetime.now().astimezone()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _emergency() -> str:
    return get_settings().emergency_number


# ------------------------------------------------------------------------------------ logging
def reading_dict(r: Reading) -> dict:
    local = _aware(r.ts).astimezone()
    return {"id": r.id, "time": local.strftime("%H:%M"), "day": r.day, "ts": local.isoformat(),
            **{k: getattr(r, k) for k in RANGES}, "flags": list(r.flags or []), "note": r.note}


def log_reading(db: Session, fields: dict, now: datetime | None = None) -> Reading:
    now = now or _now()
    clean: dict = {}
    for key, (lo, hi) in RANGES.items():
        v = fields.get(key)
        if v is None or v == "":
            continue
        num = float(v)
        if key == "temp_c" and num > hi:  # entered in °F
            num = round((num - 32) * 5 / 9, 1)
        if not lo <= num <= hi:
            raise ValueError(f"{key.replace('_', ' ')} must be between {lo} and {hi}.")
        clean[key] = int(round(num)) if key in INTS else round(num, 1)
    flags = [f for f in dict.fromkeys(fields.get("flags") or []) if f in FLAGS]
    note = str(fields.get("note") or "").strip()[:1000]
    if not clean and not flags and not note:
        raise ValueError("Add at least one measurement, symptom or note.")
    r = Reading(ts=now.astimezone(timezone.utc), day=now.date().isoformat(), flags=flags, note=note, **clean)
    db.add(r)
    db.commit()
    _sync_checkin(db, r.day)
    return r


def delete_reading(db: Session, reading_id: int) -> bool:
    r = db.get(Reading, reading_id)
    if r is None:
        return False
    day = r.day
    db.delete(r)
    db.commit()
    _sync_checkin(db, day)
    return True


def readings_for(db: Session, day: str) -> list[dict]:
    rows = db.query(Reading).filter_by(day=day).order_by(Reading.ts).all()
    return [reading_dict(r) for r in rows]


def _sync_checkin(db: Session, day: str) -> None:
    """Keep the day's summary (used by the weekly comparison) in step with the day's logs."""
    rows = db.query(Reading).filter_by(day=day).all()
    if not rows:
        return
    fields: dict = {}
    for key in ("energy", "mood", "appetite"):
        vals = [getattr(r, key) for r in rows if getattr(r, key) is not None]
        if vals:
            fields[key] = round(sum(vals) / len(vals))
    pains = [r.pain for r in rows if r.pain is not None]
    if pains:
        fields["pain"] = max(pains)
    weights = [r.weight_kg for r in sorted(rows, key=lambda r: _aware(r.ts)) if r.weight_kg is not None]
    if weights:
        fields["weight_kg"] = weights[-1]
    if fields:
        wellness.save_checkin(db, day, fields)


# ------------------------------------------------------------------------------------ helpers for the rules
def _recent(db: Session, hours: float, now: datetime) -> list[Reading]:
    since = (now - timedelta(hours=hours)).astimezone(timezone.utc)
    return [r for r in db.query(Reading).order_by(Reading.ts).all() if _aware(r.ts) >= since]


def _latest(rows: list[Reading], key: str) -> Reading | None:
    return next((r for r in reversed(rows) if getattr(r, key) is not None), None)


def _daily_means(db: Session, key: str, days: int, now: datetime) -> dict[str, float]:
    start = (now.date() - timedelta(days=days)).isoformat()
    by: dict[str, list[float]] = {}
    for r in db.query(Reading).filter(Reading.day >= start):
        v = getattr(r, key)
        if v is not None:
            by.setdefault(r.day, []).append(v)
    return {d: sum(v) / len(v) for d, v in sorted(by.items())}


def _slope(points: list[tuple[int, float]]) -> float:
    n = len(points)
    mx, my = sum(x for x, _ in points) / n, sum(y for _, y in points) / n
    den = sum((x - mx) ** 2 for x, _ in points)
    return sum((x - mx) * (y - my) for x, y in points) / den if den else 0.0


def _act(text: str, kind: str = "do") -> dict:
    return {"text": text, "kind": kind}


def _call_now() -> list[dict]:
    return [
        _act(f"Call the emergency number ({_emergency()}) or go to the nearest emergency department now. Tell them about the cancer and the current treatment.", "call"),
        _act("Do not wait for the next appointment. If possible, have someone stay with the patient.", "do"),
    ]


def _call_team_today() -> list[dict]:
    return [
        _act("Contact the oncology team today and tell them exactly what you logged. If they cannot be reached or it gets worse, go to the nearest emergency department.", "call"),
        _act("Have the list of current medicines and the latest report ready for the call.", "do"),
        _act("Log again in 1 hour so the team can see how it is changing.", "log"),
    ]


def _sig(key: str, level: str, domain: str, title: str, why: str, actions: list[dict], recheck: int | None = None) -> dict:
    return {"key": key, "level": level, "domain": domain, "title": title, "why": why, "actions": actions, "recheck": recheck}


# ------------------------------------------------------------------------------------ the rules
def candidates(db: Session, now: datetime | None = None) -> list[dict]:
    now = now or _now()
    out: list[dict] = []
    acute = _recent(db, ACUTE_HOURS, now)

    # 1. symptoms ticked in the last hours
    vessel = db.query(Scan).count() and any(f.category == "vascular" and f.certainty != "absent" for s in db.query(Scan) for f in s.findings)
    for flag, meta in FLAGS.items():
        hit = next((r for r in reversed(acute) if flag in (r.flags or [])), None)
        if hit is None:
            continue
        when = _aware(hit.ts).astimezone().strftime("%H:%M")
        if meta["level"] == "emergency":
            out.append(_sig(f"flag:{flag}", "emergency", "symptom", f"{meta['label']}", f"You logged this at {when}. It can need emergency care during cancer treatment.", _call_now()))
        elif meta["level"] == "urgent":
            why = f"You logged this at {when}."
            acts = _call_team_today()
            if flag == "neck_swelling" and vessel:
                why += " The latest scan reported a clot in a neck vein, so new neck swelling, pain or redness needs the team's assessment today."
                acts.insert(0, _act("Say that the scan reported a vein thrombosis and ask for an urgent assessment today.", "call"))
            out.append(_sig(f"flag:{flag}", "urgent", "symptom", meta["label"], why, acts, 60))
        else:
            count = sum(flag in (r.flags or []) for r in acute)
            level = "urgent" if flag == "vomiting" and count >= 2 else "watch"
            acts = [_act("Sip fluids slowly if you can swallow safely, and note how much you manage.", "do"), _act("Log again in 2 hours.", "log")]
            if level == "urgent":
                acts = _call_team_today()
            out.append(_sig(f"flag:{flag}", level, "diet", meta["label"], f"You logged this at {when}" + (f" and again since ({count} times in {ACUTE_HOURS} hours)." if count > 1 else "."), acts, 120))
    text = " ".join(f"{r.note}" for r in acute)
    if text.strip():
        if SELF_HARM.search(text):
            out.append(_sig("mind:crisis", "emergency", "mind", "You wrote something that worries us",
                            "You are not alone and help is available right now.",
                            [_act(f"Please reach out now to someone you trust, your care team, or the emergency number ({_emergency()}).", "call"), _act("If you can, stay with another person until you have spoken to someone.", "do")]))
        else:
            t = safety.triage(text)
            if t.level:
                reasons = "; ".join(h.message for h in t.hits)
                out.append(_sig("note:triage", "emergency" if t.level == safety.EMERGENCY else "urgent", "symptom", f"Your note mentions: {reasons}",
                                "The words you wrote match a warning sign.", _call_now() if t.level == safety.EMERGENCY else _call_team_today(), 60))

    # 2. vital signs (latest value in the last hours)
    r = _latest(acute, "temp_c")
    if r is not None and r.temp_c >= FEVER_C:
        out.append(_sig("vitals:fever", "urgent", "vitals", f"Temperature {r.temp_c:g} °C",
                        f"{r.temp_c:g} °C is at or above {FEVER_C:g} °C. During cancer treatment a fever can need same-day care.",
                        [_act("Recheck the temperature in 30 minutes with the same thermometer.", "check")] + _call_team_today(), 30))
    r = _latest(acute, "spo2")
    if r is not None and r.spo2 <= SPO2_URGENT:
        em = r.spo2 < SPO2_EMERGENCY
        out.append(_sig("vitals:spo2", "emergency" if em else "urgent", "vitals", f"Oxygen level {r.spo2}%", "A low oxygen reading needs prompt medical attention.",
                        _call_now() if em else [_act("Sit upright, rest, and recheck in 5 minutes (warm hands and no nail polish give truer readings).", "check")] + _call_team_today(), 5))
    r = _latest(acute, "pulse")
    if r is not None and (r.pulse >= PULSE_HIGH or r.pulse <= PULSE_LOW):
        out.append(_sig("vitals:pulse", "urgent", "vitals", f"Pulse {r.pulse}/min", "The pulse is outside the usual safe range.",
                        [_act("Sit quietly and recheck the pulse in 10 minutes.", "check")] + _call_team_today(), 10))
    r = _latest(acute, "bp_sys")
    if r is not None and (r.bp_sys < BP_SYS_LOW or r.bp_sys >= BP_SYS_HIGH):
        out.append(_sig("vitals:bp", "urgent", "vitals", f"Blood pressure {r.bp_sys}/{r.bp_dia or '?'}", "The reading is outside the usual safe range.",
                        [_act("Sit for 5 minutes and measure again.", "check")] + _call_team_today(), 10))
    r = _latest(acute, "pain")
    if r is not None and r.pain >= PAIN_URGENT:
        out.append(_sig("pain:severe", "urgent", "symptom", f"Pain {r.pain}/10", "Pain this high is worth a call to the oncology team today.",
                        [_act("Note where the pain is and what it feels like, and what you have taken for it.", "check")] + _call_team_today(), 60))

    # 3. change against your own baseline (last 2 days vs the 7 days before)
    for key, label, worse in (("pain", "Pain", "up"), ("appetite", "Appetite", "down"), ("energy", "Energy", "down"), ("mood", "Mood", "down")):
        means = _daily_means(db, key, 12, now)
        recent_days = [d for d in means if d >= (now.date() - timedelta(days=1)).isoformat()]
        base_days = [d for d in means if (now.date() - timedelta(days=9)).isoformat() <= d <= (now.date() - timedelta(days=2)).isoformat()]
        if len(base_days) < 3 or not recent_days:
            continue
        n_recent = db.query(Reading).filter(Reading.day >= (now.date() - timedelta(days=1)).isoformat(), getattr(Reading, key).isnot(None)).count()
        if n_recent < 2:
            continue  # one reading is not a trend
        base = sum(means[d] for d in base_days) / len(base_days)
        recent = sum(means[d] for d in recent_days) / len(recent_days)
        delta = recent - base if worse == "up" else base - recent
        better = -delta
        if key == "pain" and delta >= 2:
            lvl = "urgent" if delta >= 3 else "watch"
            out.append(_sig("trend:pain_up", lvl, "trend", f"Pain is rising: {recent:.1f}/10 vs your usual {base:.1f}", f"The last 2 days average {recent:.1f}/10; your previous week averaged {base:.1f}/10.",
                            [_act("Note where it hurts and what makes it better or worse.", "check"), _act("Take it to the oncology team " + ("today." if lvl == "urgent" else "at the next contact, or sooner if it keeps climbing."), "call"), _act("Log again in 4 hours.", "log")], 240))
        elif key == "appetite" and delta >= 1.5:
            lvl = "urgent" if recent <= 1.5 else "watch"
            out.append(_sig("trend:appetite_down", lvl, "diet", f"Appetite has dropped: {recent:.1f}/5 vs your usual {base:.1f}", "Eating less for days can affect strength and healing.",
                            [_act("Weigh yourself now and log it.", "check"), _act("Try small, frequent soft or moist meals and note what you manage.", "do"), _act("Tell the dietitian or oncology team" + (" today." if lvl == "urgent" else " if it lasts another day."), "call")], 240))
        elif key in ("energy", "mood") and delta >= 1.5:
            out.append(_sig(f"trend:{key}_down", "watch", "mind" if key == "mood" else "routine", f"{label} has dropped: {recent:.1f}/5 vs your usual {base:.1f}", f"The last 2 days are well below the previous week ({base:.1f}/5).",
                            [_act("Check sleep, food, fluids and pain first, since any of them can pull this down.", "check"), _act("Tell someone you trust how you feel, and mention it to the care team.", "do"), _act("Log again this evening.", "log")], 360))
        elif key == "pain" and better >= 2 and recent <= 3:
            out.append(_sig("recover:pain", "recovering", "trend", f"Pain is easing: {recent:.1f}/10 vs {base:.1f}", "A real improvement on your own numbers.",
                            [_act("Note what has helped (rest, position, routine, medicine as prescribed) so you can keep doing it.", "do"), _act("Tell the care team at the next contact.", "do")]))
        elif key in ("appetite", "energy", "mood") and better >= 1.0 and recent >= 3:
            out.append(_sig(f"recover:{key}", "recovering", "trend", f"{label} is improving: {recent:.1f}/5 vs {base:.1f}", "A real improvement on your own numbers.",
                            [_act("Note what has helped (food, rest, company, routine) so you can keep doing it.", "do"), _act("Keep logging so the trend is clear.", "log")]))

    # weight
    ws = [(r, r.weight_kg) for r in db.query(Reading).filter(Reading.weight_kg.isnot(None)).order_by(Reading.ts).all()]
    if ws:
        latest_r, latest_w = ws[-1]
        t_latest = _aware(latest_r.ts)
        past30 = [w for r, w in ws if timedelta(days=7) <= t_latest - _aware(r.ts) <= timedelta(days=30)]
        past7 = [w for r, w in ws if timedelta(days=4) <= t_latest - _aware(r.ts) <= timedelta(days=8)]
        if past30 and (max(past30) - latest_w) / max(past30) * 100 >= WEIGHT_LOSS_URGENT_30D:
            loss = (max(past30) - latest_w) / max(past30) * 100
            out.append(_sig("trend:weight_loss", "urgent", "diet", f"Weight down {loss:.1f}% in a month", f"{max(past30):g} kg → {latest_w:g} kg. Losing this much matters in cancer care.",
                            [_act("Weigh again tomorrow at the same time and log it.", "check"), _act("Tell the oncology team or dietitian today.", "call"), _act("Keep small, frequent meals going and log what you eat.", "do")], 1440))
        elif past7 and (sum(past7) / len(past7) - latest_w) / (sum(past7) / len(past7)) * 100 >= WEIGHT_LOSS_WATCH_7D:
            ref = sum(past7) / len(past7)
            out.append(_sig("trend:weight_loss", "watch", "diet", f"Weight down {((ref - latest_w) / ref) * 100:.1f}% in a week", f"About {ref:.1f} kg → {latest_w:g} kg.",
                            [_act("Weigh again tomorrow at the same time to confirm.", "check"), _act("Mention it to the dietitian or oncology team.", "call")], 1440))

    # fever that has settled, a recovering sign
    temps = [r for r in acute if r.temp_c is not None]
    wide = _recent(db, 24, now)
    if temps and temps[-1].temp_c < 37.5 and any(r.temp_c is not None and r.temp_c >= FEVER_C for r in wide):
        out.append(_sig("recover:fever", "recovering", "vitals", f"Temperature back to {temps[-1].temp_c:g} °C", "Earlier today it was above the fever line.",
                        [_act("Tell the oncology team about the fever even though it has settled.", "call"), _act("Keep checking the temperature as advised.", "check")]))

    # 4. predictions: straight-line trend over the last week, projected 3 days ahead
    for key, label, bad, cross, rate in (("appetite", "Appetite", "down", 2.0, 0.2), ("energy", "Energy", "down", 2.0, 0.2), ("mood", "Mood", "down", 2.0, 0.2), ("pain", "Pain", "up", 7.0, 0.4)):
        means = _daily_means(db, key, 7, now)
        if len(means) < 4 or f"trend:{key}_down" in {c["key"] for c in out} or f"trend:{key}_up" in {c["key"] for c in out}:
            continue
        pts = [((date.fromisoformat(d) - now.date()).days, v) for d, v in means.items()]
        s = _slope(pts)
        projected = pts[-1][1] + s * 3
        now_v = pts[-1][1]
        if bad == "down" and s <= -rate and projected <= cross and now_v > cross - 0.5:
            out.append(_sig(f"forecast:{key}", "watch", "trend", f"{label} is heading down", f"Falling about {abs(s):.1f} a day; at this pace it would reach about {max(projected, 1):.1f}/5 within 3 days.",
                            [_act("Check what changed (sleep, food, fluids, pain, medicines) and log again tonight.", "check"), _act("Mention the trend to the care team before it gets there.", "call")], 720))
        if bad == "up" and s >= rate and projected >= cross and now_v < cross + 0.5:
            out.append(_sig(f"forecast:{key}", "watch", "trend", f"{label} is heading up", f"Rising about {s:.1f} a day; at this pace it would reach about {min(projected, 10):.1f}/10 within 3 days.",
                            [_act("Note what makes it worse or better, and log again tonight.", "check"), _act("Mention the trend to the care team before it gets there.", "call")], 720))

    # 5. medicines: missed today / missed two days running
    today = now.date()
    logs: dict[int, set[str]] = {}
    for hid, d in db.query(HabitLog.habit_id, HabitLog.day):
        logs.setdefault(hid, set()).add(d)
    for h in db.query(Habit).filter_by(domain="medication", status="active"):
        hl = logs.get(h.id, set())
        created = _aware(h.created_at).astimezone().date()
        end = MED_WINDOW_END.get(h.when, MED_WINDOW_END["anytime"])
        past_window = now >= now.replace(hour=end[0], minute=end[1], second=0, microsecond=0)
        yday, y2 = (today - timedelta(days=1)).isoformat(), (today - timedelta(days=2)).isoformat()
        if created <= today - timedelta(days=2) and yday not in hl and y2 not in hl and today.isoformat() not in hl and past_window:
            out.append(_sig(f"med:missed2:{h.id}", "urgent", "medicine", f"{h.title}: no tick for 2+ days", "It has not been marked as taken for two days running.",
                            [_act("Check whether you actually took it and just forgot to tick, then tick it in the app.", "check"), _act("If doses were missed, ask your doctor or pharmacist what to do. Do not double up.", "call")], 120))
        elif created <= today and today.isoformat() not in hl and past_window:
            out.append(_sig(f"med:today:{h.id}", "watch", "medicine", f"Check: have you taken {h.title}?", f"It is past its usual time ({h.when}) and not ticked today.",
                            [_act("Check the pack or the pill organiser, and tick it in the app if you have taken it.", "check"), _act("If you have not taken it, ask your pharmacist or doctor what to do. Do not double up.", "call")], 60))

    # 6. routine and mind from the daily summary
    sleeps = [c.sleep_hours for c in db.query(CheckIn).filter(CheckIn.day >= (today - timedelta(days=1)).isoformat()) if c.sleep_hours is not None]
    if len(sleeps) >= 2 and all(s < 5 for s in sleeps):
        out.append(_sig("routine:sleep", "watch", "routine", "Under 5 hours of sleep two nights running", f"Last nights: {', '.join(f'{s:g}' for s in sleeps)} hours.",
                        [_act("Keep a regular bedtime, dim the light and screens an hour before, and note if pain or worry is keeping you awake.", "do"), _act("Mention poor sleep to the care team.", "call")], 1440))
    moods = _daily_means(db, "mood", 3, now)
    if len(moods) >= 3 and all(v <= 2 for v in list(moods.values())[-3:]):
        out.append(_sig("mind:low3", "watch", "mind", "Low mood three days running", "Your mood has been 2 or lower for three days.",
                        [_act("Talk to someone you trust today, even briefly.", "do"), _act("Tell the care team; support for low mood is part of cancer care.", "call"), _act("Try your breathing or gratitude practice from Today.", "do")], 1440))

    # 7. reports: an urgent item that is still open
    for rec in db.query(Recommendation).filter_by(source="app", urgency="urgent", status="open"):
        if _aware(rec.created_at) <= now - timedelta(hours=24):
            out.append(_sig(f"report:{rec.id}", "urgent", "report", f"Still open: {rec.text[:90]}", "This came from the latest scan and is still not marked done.",
                            [_act("Check whether it has been arranged. If not, call the oncology team today and ask for it.", "call"), _act("Mark it done in Next steps once it has happened.", "do")], 480))
    return out


# ------------------------------------------------------------------------------------ keeping the alert list in step
def sync(db: Session, now: datetime | None = None) -> list[Signal]:
    """Update the stored alerts from the current data. Returns the alerts that are new or escalated since the last sync."""
    now = now or _now()
    cands = {c["key"]: c for c in candidates(db, now)}
    existing = {s.key: s for s in db.query(Signal).all()}
    fresh: list[Signal] = []
    for key, c in cands.items():
        s = existing.get(key)
        if s is None:
            s = Signal(key=key, level=c["level"], domain=c["domain"], title=c["title"], why=c["why"], actions=c["actions"], status="open",
                       recheck_at=(now + timedelta(minutes=c["recheck"])).astimezone(timezone.utc) if c["recheck"] else None)
            db.add(s)
            fresh.append(s)
            continue
        escalated = RANK[c["level"]] > RANK.get(s.ack_level or s.level, 0) and s.status == "ack"
        if s.status == "resolved" or escalated:
            s.status, s.resolved_at, s.ack_note, s.ack_level = "open", None, "", ""
            s.first_seen = now.astimezone(timezone.utc)
            s.recheck_at = (now + timedelta(minutes=c["recheck"])).astimezone(timezone.utc) if c["recheck"] else None
            fresh.append(s)
        s.level, s.domain, s.title, s.why, s.actions, s.last_seen = c["level"], c["domain"], c["title"], c["why"], c["actions"], now.astimezone(timezone.utc)
    for key, s in existing.items():
        if key not in cands and s.status != "resolved":
            s.status, s.resolved_at = "resolved", now.astimezone(timezone.utc)
    db.commit()
    return fresh


def signal_dict(s: Signal, now: datetime | None = None) -> dict:
    now = now or _now()
    due = s.recheck_at is not None and _aware(s.recheck_at) <= now and s.status != "resolved"
    return {"id": s.id, "key": s.key, "level": s.level, "domain": s.domain, "title": s.title, "why": s.why, "actions": s.actions, "status": s.status,
            "ack_note": s.ack_note, "since": _aware(s.first_seen).astimezone().isoformat(), "recheck_at": _aware(s.recheck_at).astimezone().isoformat() if s.recheck_at else None,
            "recheck_due": due, "resolved_at": _aware(s.resolved_at).astimezone().isoformat() if s.resolved_at else None}


def active(db: Session, now: datetime | None = None) -> list[dict]:
    now = now or _now()
    rows = db.query(Signal).filter(Signal.status != "resolved").all()
    rows.sort(key=lambda s: (-RANK[s.level], s.status == "ack", s.id))
    return [signal_dict(s, now) for s in rows]


def acknowledge(db: Session, signal_id: int, note: str = "", recheck_minutes: int | None = None) -> bool:
    s = db.get(Signal, signal_id)
    if s is None:
        return False
    s.status, s.ack_level, s.ack_note = "ack", s.level, note.strip()[:500]
    s.recheck_at = (_now() + timedelta(minutes=recheck_minutes)).astimezone(timezone.utc) if recheck_minutes else None
    db.commit()
    return True


def snapshot(db: Session, now: datetime | None = None) -> dict:
    """Everything the screen needs about alerts, after re-checking against the current time and data."""
    now = now or _now()
    fresh = sync(db, now)
    items = active(db, now)
    top = max((RANK[i["level"]] for i in items if i["status"] == "open"), default=-1)
    return {
        "active": items, "fresh": [s.key for s in fresh],
        "counts": {lvl: sum(1 for i in items if i["level"] == lvl and i["status"] == "open") for lvl in RANK},
        "highest": next((k for k, v in RANK.items() if v == top), None),
        "due": sum(1 for i in items if i["recheck_due"]),
    }


def history(db: Session, limit: int = 30) -> list[dict]:
    rows = db.query(Signal).filter(Signal.status == "resolved").order_by(Signal.resolved_at.desc()).limit(limit).all()
    return [signal_dict(s) for s in rows]


def check_now(db: Session) -> list[str]:
    """The checks to do right now, from open alerts, most serious first."""
    out = []
    for s in active(db):
        if s["status"] != "open" or s["level"] == "recovering":
            continue
        for a in s["actions"]:
            if a["kind"] in ("check", "call") and a["text"] not in out:
                out.append(a["text"])
    return out[:6]


def context_lines(db: Session) -> str:
    items = [s for s in active(db) if s["status"] == "open"]
    return "\n".join(f"- [{s['level'].upper()}] {s['title']}: {s['why']}" for s in items)


# ------------------------------------------------------------------------------------ trends and predictions for the screen
def trends(db: Session, days: int = 14) -> dict:
    now = _now()
    out = []
    for key, label, unit, lower_better in (("pain", "Pain", "/10", True), ("appetite", "Appetite", "/5", False), ("energy", "Energy", "/5", False),
                                           ("mood", "Mood", "/5", False), ("temp_c", "Temperature", " °C", None), ("pulse", "Pulse", "/min", None),
                                           ("spo2", "Oxygen", "%", False), ("weight_kg", "Weight", " kg", None)):
        means = _daily_means(db, key, days, now)
        if not means:
            continue
        pts = [{"day": d, "value": round(v, 1)} for d, v in means.items()]
        slope = _slope([((date.fromisoformat(d) - now.date()).days, v) for d, v in means.items()]) if len(means) >= 4 else None
        out.append({"key": key, "label": label, "unit": unit, "series": pts, "latest": pts[-1]["value"], "slope_per_day": None if slope is None else round(slope, 2),
                    "lower_is_better": lower_better})
    return {"metrics": out, "readings_logged": db.query(Reading).count(), "days_with_logs": db.query(Reading.day).distinct().count()}
