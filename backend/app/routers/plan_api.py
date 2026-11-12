from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job, Recommendation
from app.services import advisors, jobs, nextsteps, recommendations

router = APIRouter(prefix="/api")


# ---- do-next list -----------------------------------------------------------------------------
@router.get("/nextsteps")
def get_next_steps(db: Session = Depends(get_db)) -> dict:
    items = nextsteps.do_next(db)
    return {"do_next": items, "counts": {
        "open_recommendations": sum(i["kind"] == "recommendation" for i in items),
        "findings": sum(i["kind"] == "finding" for i in items), "checks": sum(i["kind"] == "check" for i in items),
    }}


# ---- advisors' recommendations ----------------------------------------------------------------
@router.get("/recommendations")
def list_recommendations(db: Session = Depends(get_db)) -> list[dict]:
    return recommendations.listing(db)


class RecIn(BaseModel):
    text: str
    category: str = "other"
    advisor: str = ""
    rec_date: str = ""
    target_date: str = ""
    timing: str = ""


@router.post("/recommendations")
def add_recommendation(body: RecIn, db: Session = Depends(get_db)) -> list[dict]:
    """Add advice you were given in person (it has no document to quote, so it is marked as yours)."""
    rec = recommendations.add(db, text=body.text, category=body.category, advisor=body.advisor, rec_date=body.rec_date or "",
                              target_date=body.target_date, timing=body.timing, source="you")
    if rec is None:
        raise HTTPException(409, "That recommendation is already recorded (or the text is empty).")
    db.commit()
    return recommendations.listing(db)


class StatusIn(BaseModel):
    status: str
    note: str | None = None


@router.patch("/recommendations/{rec_id}")
def update_recommendation(rec_id: int, body: StatusIn, db: Session = Depends(get_db)) -> list[dict]:
    if body.status not in ("open", "done", "dismissed"):
        raise HTTPException(422, "Status must be open, done or dismissed.")
    if recommendations.set_status(db, rec_id, body.status, body.note) is None:
        raise HTTPException(404, "Not found.")
    return recommendations.listing(db)


@router.delete("/recommendations/{rec_id}", status_code=204)
def delete_recommendation(rec_id: int, db: Session = Depends(get_db)) -> None:
    rec = db.get(Recommendation, rec_id)
    if rec is None:
        raise HTTPException(404, "Not found.")
    db.delete(rec)
    db.commit()


@router.post("/recommendations/rebuild")
def rebuild_recommendations(db: Session = Depends(get_db)) -> dict:
    """Read every document again for advisors' recommendations (background; each is quoted and removable)."""
    return {"queued": jobs.enqueue_actions_rebuild(db)}


# ---- advisor packs ----------------------------------------------------------------------------
@router.get("/advisors")
def list_advisors(db: Session = Depends(get_db)) -> dict:
    packs = advisors.load_packs()
    running = {j.payload.get("pack_id"): j.status for j in db.query(Job).filter(Job.kind == "plan", Job.status.in_(("queued", "running")))}
    return {"packs": [{**advisors.describe(db, p), "running": running.get(p.id)} for p in packs.values()], "problems": advisors.load_problems()}


@router.post("/advisors/{pack_id}/run")
def run_advisor(pack_id: str, db: Session = Depends(get_db)) -> dict:
    """Queue a pack run; it is built in the background from the declared facts and checked before it is shown."""
    if pack_id not in advisors.load_packs():
        raise HTTPException(404, "Unknown advisor pack.")
    if jobs.enqueue_plan(db, pack_id) is None:
        raise HTTPException(409, "This plan is already being built.")
    return {"queued": True}


@router.get("/advisors/{pack_id}/plan")
def get_plan(pack_id: str, db: Session = Depends(get_db)) -> dict:
    return {"plan": advisors.latest_plan(db, pack_id)}
