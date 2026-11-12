"""The case file as history.

Every value (from a report or from you) is stored as a dated, sourced entry and never overwritten.
The "current" case file is derived from those entries:

* state / identity fields: the entry with the latest report date wins, so an old report can never
  replace something newer, and an entry with an unknown date can never replace a dated one;
* cumulative fields (treatment history, biomarkers, care team): all distinct entries, oldest first.

Dated clinical events (biopsy, surgery, radiotherapy, scans…) form the journey. The Case row is kept as
a materialised copy of the derived values so the rest of the app reads it as before.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Case, CaseEntry, CaseSummary, ClinicalEvent, Document, Event
from app.services import llm, safety

STATE = ("diagnosis", "stage", "current_status", "current_treatment", "primary_site", "histology")
IDENTITY = ("patient_name", "age", "sex", "hla_type", "allergies", "caregiver_contact", "goals")
CUMULATIVE = ("treatment_history", "biomarkers", "care_team", "notes")

KIND = {**{f: "state" for f in STATE}, **{f: "identity" for f in IDENTITY}, **{f: "cumulative" for f in CUMULATIVE}}
ORDER = (
    "patient_name", "age", "sex", "diagnosis", "primary_site", "histology", "stage", "biomarkers", "hla_type",
    "treatment_history", "current_treatment", "current_status", "allergies", "care_team", "goals", "caregiver_contact", "notes",
)
LABELS = {
    "patient_name": "Name", "age": "Age", "sex": "Sex", "diagnosis": "Diagnosis", "primary_site": "Primary site",
    "histology": "Histology", "stage": "Stage", "biomarkers": "Biomarkers & mutations", "hla_type": "HLA type",
    "treatment_history": "Treatment so far", "current_treatment": "Current treatment", "current_status": "Current status",
    "allergies": "Allergies", "care_team": "Care team", "goals": "Goals & preferences",
    "caregiver_contact": "Caregiver / emergency contact", "notes": "Notes",
}
EVENT_CATEGORIES = (
    "diagnosis", "biopsy", "surgery", "chemotherapy", "radiotherapy", "immunotherapy", "imaging",
    "consultation", "lab", "admission", "other",
)


def norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def today() -> str:
    return date.today().isoformat()


def _rank(e: CaseEntry) -> tuple:
    return (e.as_of or "", e.created_at, e.id)


# ------------------------------------------------------------------------------------ writes
def add_entry(db: Session, field: str, value: str, as_of: str, source: str, document_id: int | None = None, quote: str = "") -> CaseEntry | None:
    if field not in KIND:
        raise ValueError(f"unknown case field {field}")
    value = (value or "").strip()
    if not value and source != "you":
        return None
    for d in db.query(CaseEntry).filter_by(field=field, as_of=as_of or "", source=source, document_id=document_id):
        if norm(d.value) == norm(value):
            return None
    entry = CaseEntry(field=field, value=value, as_of=as_of or "", source=source, document_id=document_id, quote=quote)
    db.add(entry)
    db.flush()
    return entry


def categorize(title: str, detail: str, given: str) -> str:
    """Deterministic category from the wording, so the journey is consistent whatever the model guessed.
    The title decides (the detail often mentions other things, e.g. 'specimen sent for histopathology').
    Treatment and diagnostic wording is authoritative; weaker rules only replace a vague 'other'."""
    title_l = title.lower()
    for category, pattern in _STRONG_RULES:
        if re.search(pattern, title_l):
            return category
    if given in EVENT_CATEGORIES and given != "other":
        return given
    t = f"{title} {detail}".lower()
    for category, pattern in _WEAK_RULES:
        if re.search(pattern, t):
            return category
    return given if given in EVENT_CATEGORIES else "other"


_STRONG_RULES = (
    ("diagnosis", r"histopatholog|cytolog|pathology"),
    ("biopsy", r"biops|\bfnac\b"),
    ("surgery", r"\b(surgery|excision|resection|dissection|glossectomy|operation)\b"),
    ("radiotherapy", r"radiotherap|\brt\b|radiation|brachy"),
    ("chemotherapy", r"chemo|cisplatin|carboplatin|paclitaxel|docetaxel"),
    ("immunotherapy", r"immunotherap|pembrolizumab|nivolumab"),
)
_WEAK_RULES = (
    ("imaging", r"\bpet\b|\bct\b|\bmri\b|x-ray|xray|\busg\b|ultrasound|doppler|echo|scan"),
    ("lab", r"blood|\bcbc\b|biochem|coagulation|serolog|\bhiv\b|hbsag|hepatitis|creatinine|haemo|hemo|\bptt\b|\binr\b|clotting|group"),
    ("consultation", r"consult|opinion|review|visit|advice|advis"),
)
TREATMENT = ("surgery", "chemotherapy", "radiotherapy", "immunotherapy")
KEY_CATEGORIES = ("diagnosis", "biopsy", *TREATMENT)
TREATMENT_TAIL_DAYS = 21  # results and recovery shortly after the last treatment still belong to that phase
EPISODE_GAP_DAYS = 90  # treatments further apart than this are separate treatment episodes
DUPLICATE_WINDOW_DAYS = 3  # the same procedure often carries the procedure date on one report and the report date on another
COLLAPSING = ("biopsy", "diagnosis", *TREATMENT)  # at most one of these per day (or within the window, with a shared key word)
_GENERIC = {"procedure", "collection", "report", "reports", "impression", "result", "results", "status", "left", "right",
            "tongue", "lesion", "guided", "with", "and", "the", "for", "advice", "advised", "planned", "final", "review"}


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def _similar(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.6


def _day_gap(a: str, b: str) -> int | None:
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except ValueError:
        return None


def same_event(date_a: str, cat_a: str, title_a: str, date_b: str, cat_b: str, title_b: str) -> bool:
    """Are these two entries the same real-world event described twice (by different reports or wordings)?"""
    if cat_a != cat_b or bool(date_a) != bool(date_b):
        return False
    if norm(title_a) == norm(title_b) and date_a == date_b:
        return True
    shared = (_tokens(title_a) & _tokens(title_b)) - _GENERIC
    gap = _day_gap(date_a, date_b) if date_a else 0
    if cat_a in COLLAPSING:
        if gap == 0:
            return True  # the same kind of key event on the same day is the same event
        return gap is not None and gap <= DUPLICATE_WINDOW_DAYS and bool(shared)
    return gap == 0 and _similar(title_a, title_b)


def add_event(db: Session, event_date: str, category: str, title: str, detail: str = "", source: str = "document",
              document_id: int | None = None, quote: str = "") -> ClinicalEvent | None:
    title = (title or "").strip()
    if not title:
        return None
    category = categorize(title, detail or "", category)
    for e in db.query(ClinicalEvent).filter_by(category=category):
        if same_event(e.event_date, e.category, e.title, event_date or "", category, title):
            return None
    ev = ClinicalEvent(event_date=event_date or "", category=category, title=title, detail=(detail or "").strip(),
                       source=source, document_id=document_id, quote=quote)
    db.add(ev)
    db.flush()
    return ev


def tidy_events(db: Session) -> dict:
    """Re-apply the categorisation rules and drop near-duplicate document events (yours are never removed). Idempotent."""
    recategorised = removed = 0
    events = db.query(ClinicalEvent).order_by(ClinicalEvent.id).all()
    for e in events:
        new = categorize(e.title, e.detail, e.category)
        if new != e.category:
            e.category = new
            recategorised += 1
    kept: list[ClinicalEvent] = []
    for e in events:
        dup = next((k for k in kept if same_event(k.event_date, k.category, k.title, e.event_date, e.category, e.title)), None)
        if dup and e.source != "you":
            db.delete(e)
            removed += 1
        else:
            kept.append(e)
    db.commit()
    return {"recategorised": recategorised, "removed": removed}


def update_event(db: Session, event_id: int, *, event_date: str | None = None, title: str | None = None,
                 category: str | None = None, detail: str | None = None) -> ClinicalEvent | None:
    ev = db.get(ClinicalEvent, event_id)
    if ev is None:
        return None
    if event_date is not None:
        ev.event_date = event_date
    if title is not None and title.strip():
        ev.title = title.strip()
    if category is not None and category in EVENT_CATEGORIES:
        ev.category = category
    if detail is not None:
        ev.detail = detail.strip()
    db.commit()
    return ev


def recompute(db: Session) -> dict:
    """Refresh the materialised Case row from the entries and return the derived values."""
    values, _ = derive(db)
    case = db.get(Case, 1)
    if case is None:
        case = Case(id=1)
        db.add(case)
    for f, v in values.items():
        setattr(case, f, v)
    db.flush()
    return values


def apply_proposal(db: Session, document: Document, fields: dict[str, str], as_of: str, events: list[dict]) -> dict:
    """Store a reviewed document proposal as history. Whether a value becomes current is decided by its date."""
    added_fields = added_events = 0
    for f, v in fields.items():
        if f in KIND and add_entry(db, f, v, as_of, "document", document.id):
            added_fields += 1
    for e in events:
        if add_event(db, e.get("date", ""), e.get("category", "other"), e.get("title", ""), e.get("detail", ""), "document", document.id, e.get("quote", "")):
            added_events += 1
    recompute(db)
    db.add(Event(kind="case", title=f"History updated from {document.filename}",
                 detail=f"{added_fields} value(s) and {added_events} event(s) added as of {as_of or 'unknown date'}.",
                 ref_type="document", ref_id=document.id))
    db.commit()
    return {"values": added_fields, "events": added_events}


def save_user_edits(db: Session, new_values: dict[str, str], as_of: str | None = None) -> list[str]:
    """Record the fields the user changed on the form as new entries dated today (or `as_of`)."""
    current, _ = derive(db)
    changed = []
    for f in ORDER:
        if KIND[f] == "cumulative" or f not in new_values:
            continue  # cumulative fields are extended with add_entry, never edited as one blob
        if norm(new_values[f]) != norm(current.get(f, "")):
            add_entry(db, f, new_values[f], as_of or today(), "you")
            changed.append(f)
    if changed:
        recompute(db)
        db.add(Event(kind="case", title="Case file updated", detail="Changed: " + ", ".join(changed), ref_type="case", ref_id=1))
    db.commit()
    return changed


# ------------------------------------------------------------------------------------ reads
def derive(db: Session) -> tuple[dict[str, str], dict[str, dict]]:
    by: dict[str, list[CaseEntry]] = defaultdict(list)
    for e in db.query(CaseEntry).all():
        by[e.field].append(e)
    values: dict[str, str] = {}
    meta: dict[str, dict] = {}
    for f in ORDER:
        entries = sorted(by.get(f, []), key=_rank)
        if KIND[f] == "cumulative":
            seen, lines = set(), []
            for e in entries:
                n = norm(e.value)
                if not n or n in seen:
                    continue
                seen.add(n)
                lines.append(f"{e.as_of}: {e.value}" if e.as_of else e.value)
            values[f] = "\n".join(lines)
            meta[f] = {"as_of": entries[-1].as_of if entries else "", "source": entries[-1].source if entries else "", "entry_id": None, "document_id": None}
        elif entries:
            top = entries[-1]
            values[f] = top.value
            meta[f] = {"as_of": top.as_of, "source": top.source, "entry_id": top.id, "document_id": top.document_id}
        else:
            values[f] = ""
            meta[f] = {"as_of": "", "source": "", "entry_id": None, "document_id": None}
    return values, meta


def _fingerprint(db: Session) -> str:
    e = db.query(CaseEntry.id).order_by(CaseEntry.id.desc()).first()
    v = db.query(ClinicalEvent.id).order_by(ClinicalEvent.id.desc()).first()
    return f"{e[0] if e else 0}:{db.query(CaseEntry).count()}:{v[0] if v else 0}:{db.query(ClinicalEvent).count()}"


def detail(db: Session) -> dict:
    values, meta = derive(db)
    docs = {d.id: d.filename for d in db.query(Document).all()}
    entries: dict[str, list[CaseEntry]] = defaultdict(list)
    for e in db.query(CaseEntry).all():
        entries[e.field].append(e)
    fields = {}
    for f in ORDER:
        hist = sorted(entries.get(f, []), key=_rank, reverse=True)
        fields[f] = {
            "key": f, "label": LABELS[f], "kind": KIND[f], "value": values[f], **{k: meta[f][k] for k in ("as_of", "source", "document_id")},
            "history": [{
                "id": e.id, "value": e.value, "as_of": e.as_of, "source": e.source, "document_id": e.document_id,
                "filename": docs.get(e.document_id, ""), "quote": e.quote,
                "is_current": KIND[f] == "cumulative" or e.id == meta[f]["entry_id"],
            } for e in hist],
        }
    events = sorted(db.query(ClinicalEvent).all(), key=lambda e: (e.event_date or "9999", e.id))
    summary = db.query(CaseSummary).first()
    fp = _fingerprint(db)
    return {
        "fields": fields,
        "journey": build_journey(db),
        "events": [{
            "id": e.id, "date": e.event_date, "category": e.category, "title": e.title, "detail": e.detail,
            "source": e.source, "document_id": e.document_id, "filename": docs.get(e.document_id, ""), "quote": e.quote,
        } for e in events],
        "summary": {"text": summary.text, "generated_at": summary.generated_at.isoformat(), "stale": summary.fingerprint != fp} if summary else None,
    }


def _segments(dated: list[ClinicalEvent]) -> list[dict]:
    """Split dated events into: work-up, then alternating treatment episodes and follow-up stretches.

    Treatment events (surgery, chemo, radiotherapy, immunotherapy — including advised/planned ones) that are
    less than EPISODE_GAP_DAYS apart form one episode, which runs a few weeks past its last treatment. A
    long gap starts a new episode, so a recurrence work-up between two treatments is not hidden inside the
    first treatment."""
    from datetime import timedelta

    treat = [e for e in dated if e.category in TREATMENT]
    episodes: list[list[ClinicalEvent]] = []
    for e in treat:
        gap = _day_gap(episodes[-1][-1].event_date, e.event_date) if episodes else None
        if episodes and gap is not None and gap <= EPISODE_GAP_DAYS:
            episodes[-1].append(e)
        else:
            episodes.append([e])

    def bounds(ep: list[ClinicalEvent]) -> tuple[str, str]:
        try:
            end = (date.fromisoformat(ep[-1].event_date) + timedelta(days=TREATMENT_TAIL_DAYS)).isoformat()
        except ValueError:
            end = ep[-1].event_date
        return ep[0].event_date, end

    spans = [bounds(ep) for ep in episodes]
    labels = [", ".join(dict.fromkeys(e.category for e in ep)) for ep in episodes]
    buckets: list[list[ClinicalEvent]] = [[] for _ in range(1 + 2 * len(episodes))]  # work-up, (treatment, follow-up) × n
    for e in dated:
        slot = 0
        for i, (start, end) in enumerate(spans):
            if e.event_date >= start:
                slot = 2 * i + 1 if e.event_date <= end else 2 * i + 2
        buckets[slot].append(e)

    segments = []
    for i, evs in enumerate(buckets):
        if not evs:
            continue
        if i == 0:
            seg = {"id": "workup", "kind": "workup", "title": "Diagnosis & work-up", "subtitle": ""}
        elif i % 2 == 1:
            n = (i + 1) // 2
            seg = {"id": f"treatment-{n}", "kind": "treatment", "title": "Treatment" if len(episodes) == 1 else f"Treatment {n}", "subtitle": labels[n - 1]}
        else:
            n = i // 2
            later = n < len(episodes)
            seg = {"id": f"followup-{n}", "kind": "followup", "subtitle": "",
                   "title": "Follow-up & re-evaluation" if later else "Follow-up & surveillance"}
        segments.append({**seg, "events": evs})
    return segments


def build_journey(db: Session) -> dict:
    """Order the events into something a person (or the model) can read as one story.

    * phases come from the treatment events: everything before the first treatment is work-up; treatments close
      together form an episode (running a few weeks past its last treatment); the stretch after an episode is
      follow-up, or re-evaluation when another treatment episode follows it;
    * several lab tests on one day collapse into one item;
    * undated events are kept apart, with a prompt to date them, instead of being mixed into the timeline;
    * `milestones` is the short spine of the story (diagnosis, biopsy, treatments, latest scan)."""
    docs = {d.id: d.filename for d in db.query(Document).all()}
    events = sorted(db.query(ClinicalEvent).all(), key=lambda e: (e.event_date or "9999", e.id))

    def item(e: ClinicalEvent) -> dict:
        return {"kind": "event", "ids": [e.id], "id": e.id, "date": e.event_date, "category": e.category, "title": e.title,
                "detail": e.detail, "source": e.source, "document_id": e.document_id,
                "filename": docs.get(e.document_id, ""), "quote": e.quote}

    dated = [e for e in events if e.event_date]
    undated = [item(e) for e in events if not e.event_date]
    segments = _segments(dated)

    phases = []
    for seg in segments:
        evs = seg["events"]
        key, title = seg["id"], seg["title"]
        items: list[dict] = []
        labs_by_day: dict[str, list[ClinicalEvent]] = defaultdict(list)
        for e in evs:
            if e.category == "lab":
                labs_by_day[e.event_date].append(e)
        grouped_days = {d for d, v in labs_by_day.items() if len(v) >= 2}
        emitted: set[str] = set()
        for e in evs:
            if e.category == "lab" and e.event_date in grouped_days:
                if e.event_date in emitted:
                    continue
                emitted.add(e.event_date)
                members = labs_by_day[e.event_date]
                items.append({"kind": "group", "ids": [m.id for m in members], "date": e.event_date, "category": "lab",
                              "title": f"{len(members)} lab tests", "detail": ", ".join(m.title for m in members),
                              "events": [item(m) for m in members]})
            else:
                items.append(item(e))
        phases.append({"id": key, "kind": seg["kind"], "title": title, "subtitle": seg["subtitle"], "start": evs[0].event_date,
                       "end": evs[-1].event_date, "count": len(evs), "items": items})

    key_events = [e for e in dated if e.category in KEY_CATEGORIES]
    images = [e for e in dated if e.category == "imaging"]
    milestones = [{"date": e.event_date, "category": e.category, "title": e.title} for e in key_events]
    if images:
        latest = images[-1]
        if all(m["date"] != latest.event_date or m["title"] != latest.title for m in milestones):
            milestones.append({"date": latest.event_date, "category": "imaging", "title": f"Latest imaging: {latest.title}"})
    milestones.sort(key=lambda m: m["date"])
    return {"phases": phases, "undated": undated, "milestones": milestones,
            "overview": " → ".join(f"{m['date']} {m['title']}" for m in milestones), "total": len(events)}


def journey_text(db: Session) -> str:
    """The journey as compact, ordered text for the assistant and the summary writer."""
    j = build_journey(db)
    if not j["total"]:
        return ""
    lines = []
    if j["overview"]:
        lines.append(f"Overview: {j['overview']}")
    for p in j["phases"]:
        sub = f" — {p['subtitle']}" if p.get("subtitle") else ""
        lines.append(f"\n{p['title']}{sub} ({p['start']} to {p['end']}):")
        for it in p["items"]:
            tail = f": {it['detail']}" if it["detail"] else ""
            lines.append(f"- {it['date']} [{it['category']}] {it['title']}{tail}")
    if j["undated"]:
        lines.append("\nDate unknown (cannot be placed in the timeline):")
        lines += [f"- [{it['category']}] {it['title']}" for it in j["undated"]]
    return "\n".join(lines).strip()


def history_context(db: Session) -> str:
    """Compact history for the assistant: the journey, plus older values that were superseded."""
    parts = []
    journey = journey_text(db)
    if journey:
        parts.append("Journey (ordered into phases; dated events):\n" + journey)
    detail_ = detail(db)
    older = []
    for f in detail_["fields"].values():
        if f["kind"] == "cumulative":
            continue
        for h in f["history"]:
            if not h["is_current"] and h["value"]:
                older.append(f"- {f['label']} as of {h['as_of'] or 'unknown date'}: {h['value'][:200]} (superseded)")
    if older:
        parts.append("Earlier values (superseded by newer information):\n" + "\n".join(older[:20]))
    s = detail_["summary"]
    if s and not s["stale"]:
        parts.append("Narrative summary (AI-written from the history):\n" + s["text"])
    return "\n\n".join(parts) or "(no dated history yet)"


# ------------------------------------------------------------------------------------ summary
SUMMARY_SYSTEM = """You write a factual summary of one patient's cancer journey for their own case file, \
using ONLY the dated entries provided. Rules:
- Write in plain language, in chronological order, then end with a section "Where things stand now" based on the \
CURRENT values and the most recent dated events. The journey is already grouped into phases (work-up, treatment, \
follow-up): follow that structure and do not list every individual lab test.
- Put the date on every statement that has one. Where an entry has no date, say the date is not known.
- Keep the report's own wording for uncertainty ("appears", "could be"). Never turn a possibility into a fact.
- Do not interpret, predict, give prognosis, recommend or comment on treatment. No new information.
- If entries conflict, mention both with their dates and say which is newer, but only for clinical facts \
(diagnosis, stage, status, treatment). Do not discuss spelling variants of the name or small differences in age \
or sex; state the current values once.
Keep it under 350 words. Output only the summary."""


def _summary_input(db: Session) -> str:
    d = detail(db)
    lines = ["CURRENT VALUES (latest dated entry per field):"]
    for f in d["fields"].values():
        if f["value"]:
            lines.append(f"- {f['label']}: {f['value']} (as of {f['as_of'] or 'unknown date'}, from {f['source'] or 'n/a'})")
    lines.append("\nEARLIER VALUES:")
    for f in d["fields"].values():
        if f["kind"] == "cumulative":
            continue
        for h in f["history"]:
            if not h["is_current"] and h["value"]:
                lines.append(f"- {f['label']} as of {h['as_of'] or 'unknown date'}: {h['value']}")
    lines.append("\nJOURNEY (ordered into phases):")
    lines.append(journey_text(db) or "(no events)")
    return "\n".join(lines)


def generate_summary(db: Session) -> dict:
    text = llm.chat(SUMMARY_SYSTEM, _summary_input(db)).strip()
    if safety.lint(text):
        raise llm.LLMError("The generated summary contained wording that isn't allowed (treatment advice or certainty claims). Try again.")
    row = db.query(CaseSummary).first() or CaseSummary()
    row.text, row.fingerprint = text, _fingerprint(db)
    row.generated_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return detail(db)["summary"]


# ------------------------------------------------------------------------------------ migration
def migrate_legacy() -> int:
    """Databases created before history existed: turn the flat case file into entries.

    They get NO date (as_of ""): their true date is unknown, and stamping them with today's date would wrongly
    stop any dated report from superseding them. Set the real date from the Case file page when known."""
    with SessionLocal() as db:
        if db.query(CaseEntry.id).first():
            return 0
        case = db.get(Case, 1)
        if case is None:
            return 0
        n = 0
        for f in ORDER:
            value = getattr(case, f, "") or ""
            if value.strip() and add_entry(db, f, value, "", "you"):
                n += 1
        db.commit()
        return n
