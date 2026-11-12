"""The prioritised "Do next" list, assembled by code from the record (no model involved).

It merges three sources into one ranked list, each item keeping its reason and its source:
  * open advisor recommendations (what a clinician actually advised),
  * points the app flagged from the scans and reports (attention first),
  * checks the record is missing, weighted by how many decisions they block.
Ranking is explicit and explainable; the care-plan packs then explain it in words.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy.orm import Session

from app.models import Document
from app.services import readiness, recommendations

SCORE_ATTENTION = 100
SCORE_REC = 70
SCORE_POSSIBLE = 55
SCORE_GAP_BASE = 35
OVERDUE_BONUS = 15
RECENT_DAYS = 90
RECENT_BONUS = 10
STALE_PENALTY = 30
ADDRESSED_PENALTY = 40


def _overdue(target: str, today: date) -> bool:
    try:
        return bool(target) and date.fromisoformat(target) < today
    except ValueError:
        return False


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _collapse_findings(items: list[dict]) -> list[dict]:
    """The same finding repeated on several scans is one to-do: keep the latest, mention the rest."""
    groups: dict[str, list[dict]] = {}
    out: list[dict] = []
    for it in items:
        if it["kind"] == "finding":
            groups.setdefault(_DATE.sub("", it["title"]), []).append(it)
        else:
            out.append(it)
    for members in groups.values():
        members.sort(key=lambda m: max(_DATE.findall(m["title"]) or [""]), reverse=True)
        keep, older = members[0], members[1:]
        dates = sorted({d for m in older for d in _DATE.findall(m["title"])} - set(_DATE.findall(keep["title"])))
        if dates:
            keep["notes"] = keep["notes"] + [f"also seen on earlier scans: {', '.join(dates)}"]
        for m in older:
            keep["evidence"] += [e for e in m["evidence"] if e not in keep["evidence"]][:1]
        out.append(keep)
    return out


def do_next(db: Session, today: date | None = None) -> list[dict]:
    today = today or date.today()
    docs = {d.id: d.filename for d in db.query(Document).all()}
    items: list[dict] = []

    for r in recommendations.listing(db):
        if r["status"] != "open":
            continue
        score = SCORE_REC
        reasons = []
        age = r["age_days"]
        if r["addressed_by"]:
            score -= ADDRESSED_PENALTY
            reasons.append(f"a later {r['addressed_by'][0]['title']} on {r['addressed_by'][0]['date']} may mean this was done — confirm and mark it done")
        if age is not None and age > recommendations.STALE_DAYS:
            score -= STALE_PENALTY
            reasons.append(f"advised {age} days ago — check it is still relevant")
        elif age is not None and age <= RECENT_DAYS:
            score += RECENT_BONUS
        if _overdue(r["target_date"], today):
            score += OVERDUE_BONUS
            reasons.append(f"was due by {r['target_date']}")
        who = r["advisor"] or "an advisor"
        when = f" on {r['rec_date']}" if r["rec_date"] else ""
        items.append({
            "id": f"rec-{r['id']}", "kind": "recommendation", "severity": "advice", "score": score, "rec_id": r["id"],
            "title": r["text"], "detail": f"{who} {r['certainty']} this{when}" + (f" ({r['timing']})" if r["timing"] else "") + ".",
            "notes": reasons, "possibly_done": bool(r["addressed_by"]),
            "evidence": [{"document_id": r["document_id"], "filename": r["filename"], "quote": r["quote"]}] if r["document_id"] else [],
        })

    for i in readiness.insights(db):
        if i["id"].startswith("gap-"):
            continue
        score = {"attention": SCORE_ATTENTION, "question": SCORE_POSSIBLE, "info": 20}[i["severity"]]
        items.append({
            "id": i["id"], "kind": "finding", "severity": i["severity"], "score": score, "title": i["title"], "detail": i["detail"],
            "notes": [], "possibly_done": False,
            "evidence": [{"document_id": e["document_id"], "filename": docs.get(e["document_id"], ""), "quote": e["quote"]} for e in i["evidence"] if e.get("quote")],
        })

    items = _collapse_findings(items)

    for g in readiness.readiness(db, today)["gaps"]:
        blocks = f" Blocks: {', '.join(g['blocks'])}." if g["blocks"] else ""
        items.append({
            "id": f"gap-{g['key']}", "kind": "check", "severity": "check", "score": SCORE_GAP_BASE + 5 * g["score"],
            "title": f"Missing: {g['label']}", "detail": f"{g['why']}{blocks}", "ask": g["ask"], "notes": [], "possibly_done": False,
            "evidence": [], "gap_key": g["key"],
        })

    items.sort(key=lambda it: (-it["score"], it["title"]))
    for rank, it in enumerate(items, start=1):
        it["rank"] = rank
    return items
