"""What to settle first with the care team, built from the latest scan by plain code (no model).

The latest scan's findings are turned into three tracks of *questions to ask*: an unexplained blood-vessel finding
(urgent), a lesion that is smaller but still active (high), and agreeing the next treatment plan (high). Each
track lists concrete asks and is also recorded as open, app-suggested items you can tick off. Nothing here is a
medical order or a diagnosis: the wording stays with what the report itself says and always hands the decision to
the treating team. It also drafts the message to send them, and asks you the few questions the records cannot answer.
"""
from __future__ import annotations

import re
import threading
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import Case, Document, Recommendation, Scan
from app.services import casefile, readiness, recommendations, scan_extract, watch, wellness

APP_NAME = "Cancer-Cure Companion"
TREATMENT_STALE_DAYS = 60
SNOOZE_DAYS = 7
NECK_REASK_DAYS = 3
VERIFY_CATEGORIES = ("surgery", "radiotherapy", "chemotherapy", "immunotherapy", "biopsy")


def latest_scan(db: Session) -> Scan | None:
    scans = [s for s in readiness.scans_ordered(db) if s.scan_date]
    return max(scans, key=lambda s: s.scan_date) if scans else None


# ------------------------------------------------------------------------------------ report details
_NUM = r"(\d+(?:\.\d+)?)"


def report_details(db: Session, scan: Scan) -> dict:
    """Size, uptake and length of a blood-vessel finding, read from the report's own words (and only if stated)."""
    doc = db.get(Document, scan.document_id)
    if doc is None:
        return {}
    text = re.sub(r"\s+", " ", scan_extract.document_text(db, doc))
    for m in re.finditer(r"(?i)thrombo\w*", text):
        window = text[m.start(): m.start() + 420]
        size = re.search(rf"(?i)measures?\s*(?:approx\.?)?\s*{_NUM}\s*[x×]\s*{_NUM}\s*mm", window)
        if not size:
            continue
        suv = re.search(rf"(?i)SUV\s*max\.?\s*:?\s*{_NUM}", window)
        length = re.search(rf"(?i)length[^\d]{{0,60}}?{_NUM}\s*mm", window)
        out = {"size": f"{size.group(1)} x {size.group(2)} mm"}
        if suv:
            out["suv_max"] = suv.group(1)
        if length:
            out["length_mm"] = length.group(1)
        return out
    return {}


def _fmt_mm(v: float | None) -> str:
    return "" if v is None else f"{v:g} mm"


def _lesions(scan: Scan) -> list[dict]:
    now = {m.lesion: m for m in scan.measurements if m.kind == "current"}
    prior = {m.lesion: m for m in scan.measurements if m.kind == "prior"}
    out = []
    for key, m in now.items():
        p = prior.get(key)
        out.append({"label": m.label, "site": m.site, "now": m.size_mm, "prior": p.size_mm if p else None, "suv": m.suv_max, "target": m.is_target, "quote": m.quote})
    return out


def _evidence(db: Session, scan: Scan, quote: str) -> list[dict]:
    doc = db.get(Document, scan.document_id)
    return [{"document_id": scan.document_id, "filename": doc.filename if doc else "", "quote": quote}] if quote else []


# ------------------------------------------------------------------------------------ the three tracks
def _short(text: str) -> str:
    """The finding without the report's hedge, which is kept separately as the report's own wording."""
    return re.split(r"\s+(?:with|could|appears?|possibly|likely|suspicious)\b", text.rstrip(". "), maxsplit=1)[0]


def tracks(db: Session) -> list[dict]:
    scan = latest_scan(db)
    if scan is None:
        return []
    when = f"{scan.modality or 'scan'} of {scan.scan_date}"
    out: list[dict] = []

    vascular = [f for f in scan.findings if f.category == "vascular" and f.certainty != "absent"]
    if vascular:
        f = vascular[0]
        det = report_details(db, scan)
        facts = []
        brief = ""
        if det:
            bits = [f"about {det['size']} in cross-section"] + ([f"length about {det['length_mm']} mm"] if "length_mm" in det else []) + ([f"SUVmax {det['suv_max']}"] if "suv_max" in det else [])
            facts.append("Reported size: " + ", ".join(bits) + " (from the report text).")
            brief = "Reported size: " + ", ".join(bits) + "."
        short = _short(f.text)
        out.append({
            "id": "vessel", "priority": "urgent", "label": "Urgent", "title": short, "wording": f.text.rstrip(". "), "brief": brief,
            "why": "The report describes a clot in a major neck vein with increased uptake and says it could be tumour rather than a simple clot. "
                   "That needs the treating team's assessment soon, not at the next routine visit. If they cannot see the patient promptly, ask whether to go to an emergency department.",
            "facts": facts,
            "asks": [
                "Can you assess the reported vein thrombosis urgently, rather than at the next routine appointment?",
                "Should a colour Doppler ultrasound of the vein be arranged?",
                "Is a contrast CT or MRI needed to tell tumour involvement of the vein from a simple clot?",
                "After you weigh the bleeding risk, does the patient need blood-thinning (anticoagulant) treatment?",
                "Is there any immediate risk of the clot travelling to the lungs, and what should we watch for?",
            ],
            "recs": [
                {"text": f"Urgent assessment of the reported {short[0].lower() + short[1:]}", "category": "referral"},
                {"text": "Colour Doppler ultrasound of the affected neck vein, if the treating team advises it", "category": "imaging"},
                {"text": "Contrast CT or MRI to tell tumour involvement of the vein from a clot, if the treating team advises it", "category": "imaging"},
            ],
            "urgency": "urgent", "evidence": _evidence(db, scan, f.quote), "go_now": "Sudden breathlessness, chest pain, or fast-growing swelling of the neck or face: call the emergency number now.",
        })

    lesions = [l for l in _lesions(scan) if l["target"] and l["suv"] is not None and l["suv"] >= readiness.RESIDUAL_SUV]
    primary = [f for f in scan.findings if f.category == "primary" and f.certainty != "absent"]
    if lesions or primary:
        top = max(lesions, key=lambda l: l["suv"]) if lesions else None
        label = (top["label"] if top else "primary-site lesion")
        facts = []
        if top:
            move = f"{_fmt_mm(top['prior'])} → {_fmt_mm(top['now'])}" if top["prior"] is not None else _fmt_mm(top["now"])
            facts.append(f"{top['label']}: {move}, SUVmax {top['suv']:g} — smaller, but still metabolically active.")
        out.append({
            "id": "residual", "priority": "high", "label": "High priority", "title": f"Persistent active {label.lower()}",
            "wording": primary[0].text.rstrip(". ") if primary else "",
            "brief": f"{label} now {_fmt_mm(top['now'])}, SUVmax {top['suv']:g}." if top else "",
            "why": "The lesion shrank but still takes up the tracer, and the report words it as possibly recurrent disease. Only the treating team can say whether it is live tumour or treatment change.",
            "facts": facts,
            "asks": [
                "Does this represent viable cancer or post-treatment change?",
                "Is a repeat biopsy appropriate?",
                "Is an MRI of the primary site and neck needed?",
                "Is further surgery or another treatment being considered?",
                "What treatment options are available if active cancer is confirmed?",
            ],
            "recs": [{"text": f"Ask the head-and-neck specialist to review the persistent active {label.lower()}" + (f" ({_fmt_mm(top['now'])}, SUVmax {top['suv']:g})" if top else ""), "category": "referral"}],
            "urgency": "high", "evidence": _evidence(db, scan, (primary[0].quote if primary else (top or {}).get("quote", ""))), "go_now": "",
        })

    if out or scan.reported_label:
        out.append({
            "id": "strategy", "priority": "high", "label": "High priority", "title": "Agree the next treatment plan", "wording": "", "brief": "",
            "why": f"The {when} shows a response but also open questions. A joint review lets the surgeon, medical oncologist, radiation oncologist and radiologist agree the plan together.",
            "facts": [f"Report conclusion: {scan.reported_label}."] if scan.reported_label else [],
            "asks": [
                "Can the surgical, medical and radiation oncologists and the radiologist or nuclear-medicine doctor review the case together?",
                "Given the earlier treatment, this scan and the examination, what are the options and what do you advise?",
            ],
            "recs": [{"text": "Multidisciplinary review (surgical, medical and radiation oncology, radiology) to agree the next treatment plan", "category": "referral"}],
            "urgency": "high", "evidence": _evidence(db, scan, scan.reported_quote), "go_now": "",
        })
    return out


_sync_lock = threading.Lock()


def sync(db: Session) -> int:
    """Record each track's items as open, app-suggested items (idempotent, safe under concurrent calls).
    Earlier scans' suggestions are retired."""
    scan = latest_scan(db)
    if scan is None:
        return 0
    with _sync_lock:
        added = 0
        who = f"{APP_NAME}, from the {scan.scan_date} {scan.modality or 'scan'}".strip()
        for t in tracks(db):
            quote = t["evidence"][0]["quote"] if t["evidence"] else ""
            for r in t["recs"]:
                if recommendations.add(db, text=r["text"], category=r["category"], advisor=who, rec_date=scan.scan_date, certainty="suggested",
                                       source="app", document_id=scan.document_id, quote=quote, urgency=t["urgency"]):
                    added += 1
        current = {casefile.norm(r["text"]) for t in tracks(db) for r in t["recs"]}
        seen: set[str] = set()
        for r in db.query(Recommendation).filter(Recommendation.source == "app").order_by(Recommendation.id):
            if r.status == "open" and r.rec_date < scan.scan_date:
                r.status, r.note = "dismissed", f"Replaced by the suggestions from the {scan.scan_date} scan."
            if r.status == "open" and r.rec_date == scan.scan_date and casefile.norm(r.text) not in current:
                db.delete(r)  # wording from an earlier version of these suggestions
                continue
            key = f"{r.rec_date}|{casefile.norm(r.text)}"
            if key in seen:
                db.delete(r)  # a duplicate left by an earlier concurrent run
            seen.add(key)
        db.commit()
        return added


# ------------------------------------------------------------------------------------ questions for you
def _snoozed(db: Session, key: str) -> bool:
    until = wellness.get_setting(db, f"q:{key}")
    return bool(until) and until >= date.today().isoformat()


def _set_mark(db: Session, key: str, when: date) -> None:
    wellness.set_setting(db, f"q:{key}", when.isoformat())


def _treatment_is_stale(db: Session, today: date) -> bool:
    values, meta = casefile.derive(db)
    if not values["current_treatment"]:
        return True
    stamp = meta["current_treatment"]["as_of"]
    return not _valid(stamp) or (today - date.fromisoformat(stamp)).days > TREATMENT_STALE_DAYS


def questions(db: Session) -> list[dict]:
    out: list[dict] = []
    today = date.today()

    if _treatment_is_stale(db, today) and not _snoozed(db, "treatment_status"):
        out.append({"id": "treatment_status", "text": "Is any cancer treatment going on right now?",
                    "why": "Whether the patient is on immunotherapy, chemotherapy or radiotherapy changes how a new finding is handled, and the records do not say clearly.",
                    "options": [{"value": "on", "label": "Yes, still receiving treatment"}, {"value": "finished", "label": "No, treatment has finished"}, {"value": "unsure", "label": "Not sure"}],
                    "detail_label": "Which treatment? (optional)"})

    if any(t["id"] == "vessel" for t in tracks(db)):
        last = wellness.get_setting(db, "q:neck_answered")
        if not last or last < (today - timedelta(days=NECK_REASK_DAYS)).isoformat():
            out.append({"id": "neck_symptoms", "text": "Is the neck on the affected side swollen, painful or red?",
                        "why": "This helps the team judge how urgent the reported vein clot is. It is saved to today's check-in.",
                        "options": [{"value": "yes", "label": "Yes, swollen, painful or red"}, {"value": "no", "label": "No"}, {"value": "unsure", "label": "Not sure"}]})

    verify = [r for r in recommendations.listing(db) if r["status"] == "open" and r["nature"] == "verify" and r["category"] in VERIFY_CATEGORIES]
    verify.sort(key=lambda r: r["rec_date"], reverse=True)
    for r in verify:
        if len([q for q in out if q["id"].startswith("rec-")]) >= 3:
            break
        if _snoozed(db, f"rec-{r['id']}"):
            continue
        who = r["advisor"] or "an advisor"
        out.append({"id": f"rec-{r['id']}", "text": f"Was this actually carried out? “{r['text']}”",
                    "why": f"{who} planned this on {r['rec_date']}. A plan is not proof that it happened, so the app keeps it open until you say.",
                    "options": [{"value": "done", "label": "Yes, it was done"}, {"value": "not_done", "label": "No, it was not done"}, {"value": "unsure", "label": "Not sure"}]})
    return out


def _valid(stamp: str) -> bool:
    try:
        date.fromisoformat(stamp)
        return True
    except ValueError:
        return False


def answer(db: Session, qid: str, value: str, detail: str = "") -> dict:
    today = date.today()
    if value == "unsure":
        _set_mark(db, qid, today + timedelta(days=SNOOZE_DAYS))
        return {"ok": True, "alert": None}
    if qid == "treatment_status":
        if value not in ("on", "finished"):
            raise ValueError("Unknown answer.")
        text = "Still receiving treatment" if value == "on" else "Treatment has finished"
        if detail.strip():
            text += f": {detail.strip()[:200]}"
        casefile.add_entry(db, "current_treatment", f"{text} (confirmed by you)", today.isoformat(), "you")
        db.commit()
        return {"ok": True, "alert": None}
    if qid == "neck_symptoms":
        if value not in ("yes", "no"):
            raise ValueError("Unknown answer.")
        alert = None
        if value == "yes":
            watch.log_reading(db, {"flags": ["neck_swelling"], "note": "Neck swollen, painful or red (answered in Next steps)"})
            sig = next((s for s in watch.snapshot(db)["active"] if s["key"] == "flag:neck_swelling"), None)
            if sig:
                alert = {"level": sig["level"], "message": f"**{sig['title']}.** " + " ".join(a["text"] for a in sig["actions"][:2])}
        else:
            watch.log_reading(db, {"note": "No neck swelling, pain or redness (answered in Next steps)"})
        _set_mark(db, "neck_answered", today)
        return {"ok": True, "alert": alert}
    if qid.startswith("rec-"):
        rec_id = int(qid[4:])
        if value == "done":
            ok = recommendations.set_status(db, rec_id, "done", "Confirmed done by you.")
        elif value == "not_done":
            ok = recommendations.set_status(db, rec_id, "open", "Confirmed by you as not carried out.", verified="not_done")
        else:
            raise ValueError("Unknown answer.")
        if ok is None:
            raise LookupError("Not found.")
        return {"ok": True, "alert": None}
    raise LookupError("Unknown question.")


# ------------------------------------------------------------------------------------ message to the care team
def message(db: Session) -> dict:
    scan = latest_scan(db)
    if scan is None:
        return {"available": False, "text": "", "attach": ""}
    doc = db.get(Document, scan.document_id)
    case = db.get(Case, 1)
    name = (case.patient_name if case else "") or ""
    lines = [f"Doctor, we have received the {scan.modality or 'scan'} report dated {scan.scan_date}" + (f" for {name}." if name else ".")]
    moves = [f"{l['label']} {_fmt_mm(l['prior'])} → {_fmt_mm(l['now'])}" for l in _lesions(scan) if l["target"] and l["prior"] is not None and l["now"] is not None]
    if scan.reported_label:
        lines.append(f"\nThe report concludes: {scan.reported_label}" + (f" ({'; '.join(moves)})." if moves else "."))
    ts = tracks(db)
    concerns = []
    for t in ts:
        if t["id"] not in ("vessel", "residual"):
            continue
        parts = [t["title"] + "."]
        if t["brief"]:
            parts.append(t["brief"])
        if t["wording"]:
            parts.append(f"The report says: “{t['wording']}”.")
        concerns.append(" ".join(parts))
    if concerns:
        lines.append("\nWe are concerned about:")
        lines += [f"{n}. {c}" for n, c in enumerate(concerns, start=1)]
    asks = []
    if any(t["id"] == "vessel" for t in ts):
        asks.append("Could you please advise on an urgent consultation and the investigations needed for the vein thrombosis, for example a Doppler ultrasound and any further contrast imaging, and whether anticoagulation needs to be considered?")
    if any(t["id"] == "residual" for t in ts):
        asks.append("We would also like to understand whether the persistent active lesion needs a repeat biopsy or an MRI, and whether it represents active disease.")
    asks.append("Could the case be reviewed jointly by the treating specialists, and could you advise what the next treatment plan should be?")
    lines += [""] + asks + ["", "Thank you."]
    return {"available": True, "text": "\n".join(lines), "attach": doc.filename if doc else ""}
