"""Evaluates the structured record against the requirements catalogue and derives next-step insights.

Everything here is deterministic. `unknown` (no data) is deliberately different from `negative`
(tested, nothing found) and `not_done`: missing data is never interpreted as a result.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from app.models import Case, Document, Fact, Finding, Measurement, Scan
from app.services import requirements as req
from app.services import response

RECENT_IMAGING_DAYS = 90
RECENT_LABS_DAYS = 45
RESIDUAL_SUV = 2.5  # uptake above this in a target lesion is worth asking about
DISCREPANCY_POINTS = 1.0


def _parse(d: str) -> date | None:
    try:
        return date.fromisoformat(d)
    except (TypeError, ValueError):
        return None


def _age_days(d: str, today: date) -> int | None:
    parsed = _parse(d)
    return (today - parsed).days if parsed else None


def case_text(case: Case | None) -> str:
    if not case:
        return ""
    return " ".join(str(getattr(case, f) or "") for f in ("diagnosis", "primary_site", "histology", "notes"))


# ------------------------------------------------------------------------------------ progress

def scans_ordered(db: Session) -> list[Scan]:
    return sorted(db.query(Scan).all(), key=lambda s: (s.scan_date or "", s.id))


def scan_comparison(scan: Scan) -> response.Comparison | None:
    cur = [response.Point(m.lesion, m.label, m.size_mm) for m in scan.measurements if m.is_target and m.kind == "current" and m.size_mm is not None]
    pri = [response.Point(m.lesion, m.label, m.size_mm) for m in scan.measurements if m.is_target and m.kind == "prior" and m.size_mm is not None]
    return response.compare(pri, cur)


def progress(db: Session) -> dict:
    scans = scans_ordered(db)
    series: dict[str, dict] = {}
    for s in scans:
        for m in s.measurements:
            if m.size_mm is None or not m.point_date:
                continue
            entry = series.setdefault(m.lesion, {"lesion": m.lesion, "label": m.label, "is_target": m.is_target, "points": []})
            entry["points"].append({
                "date": m.point_date, "size_mm": m.size_mm, "suv_max": m.suv_max, "kind": m.kind,
                "scan_id": s.id, "document_id": s.document_id, "quote": m.quote,
            })
    for entry in series.values():
        # A study's own measurement outranks a "prior" value quoted by a later report for the same date.
        best: dict[str, dict] = {}
        for p in entry["points"]:
            cur = best.get(p["date"])
            if cur is None or (cur["kind"] == "prior" and p["kind"] == "current"):
                best[p["date"]] = p
        entry["points"] = sorted(best.values(), key=lambda p: p["date"])

    out_scans = []
    for s in scans:
        cmp = scan_comparison(s)
        computed = None
        if cmp:
            computed = {
                "sum_prior": cmp.sum_prior, "sum_now": cmp.sum_now, "pct_change": cmp.pct_change,
                "category": cmp.category, "category_label": cmp.category_label, "lesions": list(cmp.lesions), "caveat": cmp.caveat,
            }
        discrepancy = None
        if cmp and s.reported_pct is not None and abs(abs(s.reported_pct) - abs(cmp.pct_change)) > DISCREPANCY_POINTS:
            discrepancy = f"The report states {s.reported_pct:g}% but the lesion sizes it lists give {abs(cmp.pct_change):g}%."
        out_scans.append({
            "id": s.id, "document_id": s.document_id, "modality": s.modality, "date": s.scan_date,
            "comparator_date": s.comparator_date, "comparator_modality": s.comparator_modality,
            "reported": {"label": s.reported_label, "criteria": s.reported_criteria, "sum_prior": s.reported_sum_prior,
                         "sum_now": s.reported_sum_now, "pct": s.reported_pct, "quote": s.reported_quote},
            "computed": computed, "discrepancy": discrepancy,
            "findings": [{"id": f.id, "text": f.text, "category": f.category, "certainty": f.certainty, "quote": f.quote} for f in s.findings],
            "measurements": [{"id": m.id, "label": m.label, "site": m.site, "kind": m.kind, "date": m.point_date,
                              "size_mm": m.size_mm, "suv_max": m.suv_max, "is_target": m.is_target, "basis": m.basis} for m in s.measurements],
        })
    return {"series": list(series.values()), "scans": out_scans}


# ------------------------------------------------------------------------------------ record

def evaluate_requirements(db: Session, today: date | None = None) -> list[dict]:
    today = today or date.today()
    case = db.get(Case, 1)
    profile = req.profile_for(case_text(case))
    facts = {f.key: f for f in db.query(Fact).all()}
    docs = db.query(Document).all()
    scans = scans_ordered(db)
    prog = progress(db)

    free_text = ""
    if case:
        free_text = " ".join(str(getattr(case, f) or "") for f in ("biomarkers", "notes", "current_status", "treatment_history", "diagnosis"))

    out = []
    for r in req.applicable(profile):
        status, value, source, doc_id, note = "unknown", "", "", None, ""
        fact = facts.get(r.key)
        if fact:
            status, value, source, doc_id = fact.status, fact.value, "fact", fact.document_id
        elif r.key == "recent_imaging":
            dates = [s.scan_date for s in scans if s.scan_date] + [d.doc_date for d in docs if d.doc_type == "imaging" and d.doc_date]
            ages = [a for a in (_age_days(d, today) for d in dates) if a is not None]
            if ages and min(ages) <= RECENT_IMAGING_DAYS:
                status, source, value = "present", "derived", f"Latest imaging {min(ages)} days ago"
            elif ages:
                note = f"Latest imaging was {min(ages)} days ago."
        elif r.key == "imaging_trend":
            if any(len({p["date"] for p in s["points"]}) >= 2 for s in prog["series"] if s["is_target"]):
                status, source, value = "present", "derived", "Target lesions measured at two or more dates"
        elif r.key == "labs_recent":
            ages = [a for a in (_age_days(d.doc_date, today) for d in docs if d.doc_type == "lab") if a is not None]
            if ages and min(ages) <= RECENT_LABS_DAYS:
                status, source, value = "present", "document", f"Lab report {min(ages)} days ago"
        else:
            if r.case_field and case and getattr(case, r.case_field, ""):
                status, source, value = "present", "case", str(getattr(case, r.case_field))[:200]
            elif r.case_regex and re.search(r.case_regex, free_text, re.I):
                status, source, value = "present", "case", "Mentioned in the case file"
            elif r.doc_type:
                match = next((d for d in docs if d.doc_type == r.doc_type), None)
                if match:
                    status, source, doc_id, value = "present", "document", match.id, f"Document on file: {match.filename}"
        out.append({
            "key": r.key, "label": r.label, "group": r.group, "why": r.why, "ask": r.ask,
            "status": status, "met": status in ("present", "negative"), "value": value, "source": source,
            "document_id": doc_id, "note": note,
        })
    return out


def readiness(db: Session, today: date | None = None) -> dict:
    items = evaluate_requirements(db, today)
    by_key = {i["key"]: i for i in items}
    decisions = []
    unlock_count: dict[str, list[str]] = defaultdict(list)
    hard_blockers: dict[str, list[str]] = defaultdict(list)
    for d in req.DECISIONS:
        needs = [k for k in d.needs if k in by_key]
        met = [k for k in needs if by_key[k]["met"]]
        unmet = [k for k in needs if not by_key[k]["met"]]
        hard_unmet = [k for k in d.hard if k in by_key and not by_key[k]["met"]]
        status = "blocked" if hard_unmet else ("partial" if unmet else "ready")
        for k in unmet:
            unlock_count[k].append(d.title)
        for k in hard_unmet:
            hard_blockers[k].append(d.title)
        decisions.append({
            "id": d.id, "title": d.title, "question": d.question, "status": status,
            "met": [by_key[k]["label"] for k in met], "unmet": [{"key": k, "label": by_key[k]["label"], "status": by_key[k]["status"]} for k in unmet],
            "blocked_by": [by_key[k]["label"] for k in hard_unmet],
        })
    gaps = []
    for k, titles in unlock_count.items():
        item = by_key[k]
        gaps.append({**item, "unlocks": titles, "blocks": hard_blockers.get(k, []),
                     "score": len(titles) + 2 * len(hard_blockers.get(k, []))})
    gaps.sort(key=lambda g: (-g["score"], g["label"]))
    return {"profile": req.profile_for(case_text(db.get(Case, 1))), "requirements": items, "decisions": decisions, "gaps": gaps}


# ------------------------------------------------------------------------------------ insights

def insights(db: Session, today: date | None = None) -> list[dict]:
    """Prioritised things worth raising with the oncologist, each tied to its evidence.
    These are questions and observations, never recommendations about treatment."""
    today = today or date.today()
    out: list[dict] = []
    scans = scans_ordered(db)

    for s in scans:
        ev = lambda quote: [{"document_id": s.document_id, "quote": quote}] if quote else [{"document_id": s.document_id, "quote": ""}]
        for f in s.findings:
            when = s.scan_date or "this scan"
            if f.category == "vascular" and f.certainty != "absent":
                out.append({"id": f"vascular-{f.id}", "severity": "attention", "title": f"Blood-vessel finding on the {when} scan",
                    "detail": f"The report describes: {f.text.rstrip('. ')}. Ask the care team whether it needs any action, whether it is related to the cancer, "
                              "and which symptoms (for example new swelling, pain, redness or breathlessness) should trigger an urgent call.",
                    "evidence": ev(f.quote)})
            elif f.certainty == "possible" and f.category in ("primary", "nodal", "distant", "other"):
                out.append({"id": f"possible-{f.id}", "severity": "question", "title": f"Not yet confirmed: {f.text}",
                    "detail": "The report words this as possible rather than certain. Ask what would confirm or exclude it and how the answer would change the plan.",
                    "evidence": ev(f.quote)})
        cur_targets = [m for m in s.measurements if m.kind == "current" and m.is_target and m.suv_max is not None and m.suv_max >= RESIDUAL_SUV]
        cmp = scan_comparison(s)
        if cmp and cmp.category == "partial_response" and cur_targets:
            names = ", ".join(f"{m.label} (SUVmax {m.suv_max:g})" for m in cur_targets)
            out.append({"id": f"residual-{s.id}", "severity": "question", "title": "Smaller, but still metabolically active",
                "detail": f"Targets shrank {abs(cmp.pct_change):g}% yet still show uptake: {names}. Ask how the team interprets residual activity and what follow-up it means.",
                "evidence": ev(cur_targets[0].quote)})
        if cmp and s.reported_pct is not None and abs(abs(s.reported_pct) - abs(cmp.pct_change)) > DISCREPANCY_POINTS:
            out.append({"id": f"discrepancy-{s.id}", "severity": "info", "title": "Report percentage does not match its own measurements",
                "detail": f"The report states {s.reported_pct:g}% but the sizes it lists give {abs(cmp.pct_change):g}%. Worth asking the radiologist to confirm.",
                "evidence": ev(s.reported_quote)})

    for g in readiness(db, today)["gaps"][:6]:
        blocks = f" It currently blocks: {', '.join(g['blocks'])}." if g["blocks"] else ""
        status = {"not_done": "documented as not done", "unknown": "not in the record"}.get(g["status"], g["status"])
        out.append({"id": f"gap-{g['key']}", "severity": "question", "title": f"Missing: {g['label']}",
            "detail": f"{g['why']} Status: {status}.{blocks}" + (f" Ask: “{g['ask']}”" if g["ask"] else ""), "evidence": []})

    if scans and not any(i["id"].startswith("gap-recent_imaging") for i in out):
        latest = max((s.scan_date for s in scans if s.scan_date), default="")
        age = _age_days(latest, today)
        if age is not None and age > RECENT_IMAGING_DAYS:
            out.append({"id": "stale-imaging", "severity": "question", "title": f"Latest scan is {age} days old",
                "detail": "Ask when the next scan is planned.", "evidence": []})

    order = {"attention": 0, "question": 1, "info": 2}
    out.sort(key=lambda i: order[i["severity"]])
    return out


def context_block(db: Session, today: date | None = None) -> str:
    """Compact, model-readable summary of computed facts so the assistant never re-derives numbers."""
    prog = progress(db)
    lines: list[str] = []
    for s in prog["scans"]:
        head = f"- {s['modality'] or 'Scan'} {s['date'] or '(date unknown)'} [D{s['document_id']}]"
        if s["comparator_date"]:
            head += f" compared with {s['comparator_modality'] or 'previous study'} {s['comparator_date']}"
        lines.append(head)
        if s["reported"]["label"]:
            lines.append(f"  report states: {s['reported']['label']}")
        if s["computed"]:
            c = s["computed"]
            lines.append(f"  computed: sum of target lesions {c['sum_prior']} mm -> {c['sum_now']} mm ({c['pct_change']:+g}%), {c['category_label']}. {c['caveat']}")
        for m in s["measurements"]:
            if m["kind"] == "current":
                suv = f", SUVmax {m['suv_max']:g}" if m["suv_max"] is not None else ""
                lines.append(f"  {m['label']}: {m['size_mm']:g} mm{suv}")
        for f in s["findings"]:
            lines.append(f"  finding ({f['certainty']}): {f['text']}")
    ready = readiness(db, today)
    for d in ready["decisions"]:
        if d["status"] != "ready":
            lines.append(f"- {d['title']}: {d['status']}; missing {', '.join(u['label'] for u in d['unmet'])}")
    return "\n".join(lines) or "(no structured scan data or readiness information yet)"
