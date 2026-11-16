from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import watch

router = APIRouter(prefix="/api/watch")


@router.get("/flags")
def get_flags() -> list[dict]:
    return [{"key": k, "label": v["label"], "level": v["level"]} for k, v in watch.FLAGS.items()]


@router.get("/readings")
def get_readings(day: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    return watch.readings_for(db, day or datetime.now().date().isoformat())


@router.post("/readings")
def post_reading(body: dict, db: Session = Depends(get_db)) -> dict:
    """Log how things are right now. The reply carries any alert this log raised, so the next step is shown at once."""
    try:
        r = watch.log_reading(db, body)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None
    snap = watch.snapshot(db)
    return {"reading": watch.reading_dict(r), "snapshot": snap, "check_now": watch.check_now(db)}


@router.delete("/readings/{reading_id}", status_code=204)
def remove_reading(reading_id: int, db: Session = Depends(get_db)) -> None:
    if not watch.delete_reading(db, reading_id):
        raise HTTPException(404, "Not found.")


@router.get("/signals")
def get_signals(db: Session = Depends(get_db)) -> dict:
    return {**watch.snapshot(db), "check_now": watch.check_now(db), "history": watch.history(db)}


@router.get("/summary")
def get_summary(db: Session = Depends(get_db)) -> dict:
    s = watch.snapshot(db)
    return {"counts": s["counts"], "highest": s["highest"], "due": s["due"], "fresh": s["fresh"],
            "headline": next((i["title"] for i in s["active"] if i["status"] == "open" and i["level"] in ("emergency", "urgent")), "")}


class AckIn(BaseModel):
    note: str = ""
    recheck_minutes: int | None = None


@router.post("/signals/{signal_id}/ack")
def ack_signal(signal_id: int, body: AckIn, db: Session = Depends(get_db)) -> dict:
    if not watch.acknowledge(db, signal_id, body.note, body.recheck_minutes):
        raise HTTPException(404, "Not found.")
    return watch.snapshot(db)


@router.get("/trends")
def get_trends(db: Session = Depends(get_db)) -> dict:
    return watch.trends(db)
