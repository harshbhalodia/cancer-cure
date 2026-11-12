from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Habit
from app.services import jobs, wellness

router = APIRouter(prefix="/api/wellness")


def _check_day(day: str | None) -> str:
    try:
        return wellness._day(day)
    except ValueError:
        raise HTTPException(422, "day must look like 2026-11-12.") from None


@router.get("/today")
def get_today(day: str | None = None, db: Session = Depends(get_db)) -> dict:
    return wellness.today_view(db, _check_day(day))


@router.get("/trends")
def get_trends(day: str | None = None, db: Session = Depends(get_db)) -> dict:
    return wellness.trends(db, _check_day(day))


@router.get("/library")
def get_library(db: Session = Depends(get_db)) -> dict:
    return {"starters": wellness.library(db), "gentle_set": list(wellness.GENTLE_SET), "domains": [{"id": k, **v} for k, v in wellness.DOMAINS.items()]}


class HabitIn(BaseModel):
    domain: str
    title: str
    detail: str = ""
    when: str = "anytime"
    dose: str = ""
    prescriber: str = ""


@router.post("/habits")
def add_habit(body: HabitIn, db: Session = Depends(get_db)) -> dict:
    habit = wellness.add_habit(db, domain=body.domain, title=body.title, detail=body.detail, when=body.when, dose=body.dose,
                               prescriber=body.prescriber, source="you")
    if habit is None:
        raise HTTPException(409, "That is already in your plan (or the title is empty).")
    db.commit()
    return {"id": habit.id}


class HabitPatch(BaseModel):
    title: str | None = None
    detail: str | None = None
    when: str | None = None
    dose: str | None = None
    prescriber: str | None = None
    status: str | None = None


@router.patch("/habits/{habit_id}")
def patch_habit(habit_id: int, body: HabitPatch, db: Session = Depends(get_db)) -> dict:
    if wellness.update_habit(db, habit_id, body.model_dump(exclude_none=True)) is None:
        raise HTTPException(404, "Not found.")
    return {"ok": True}


@router.delete("/habits/{habit_id}", status_code=204)
def delete_habit(habit_id: int, db: Session = Depends(get_db)) -> None:
    habit = db.get(Habit, habit_id)
    if habit is None:
        raise HTTPException(404, "Not found.")
    db.delete(habit)
    db.commit()


class LogIn(BaseModel):
    day: str | None = None
    done: bool = True


@router.put("/habits/{habit_id}/log")
def log_habit(habit_id: int, body: LogIn, db: Session = Depends(get_db)) -> dict:
    day = _check_day(body.day)
    if date.fromisoformat(day) > date.today():
        raise HTTPException(422, "You can't tick something off for a future day.")
    if not wellness.set_done(db, habit_id, day, body.done):
        raise HTTPException(404, "Not found.")
    return {"ok": True}


class StarterIn(BaseModel):
    keys: list[str]


@router.post("/starters")
def add_starters(body: StarterIn, db: Session = Depends(get_db)) -> dict:
    return {"added": wellness.add_starters(db, body.keys)}


@router.put("/checkin")
def put_checkin(body: dict, db: Session = Depends(get_db)) -> dict:
    day = _check_day(body.pop("day", None))
    if date.fromisoformat(day) > date.today():
        raise HTTPException(422, "You can't check in for a future day.")
    try:
        return wellness.save_checkin(db, day, body)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None


class VisionIn(BaseModel):
    text: str


@router.put("/vision")
def put_vision(body: VisionIn, db: Session = Depends(get_db)) -> dict:
    wellness.set_setting(db, "vision", body.text)
    return {"vision": wellness.get_setting(db, "vision")}


@router.post("/medicines/scan")
def scan_medicines(db: Session = Depends(get_db)) -> dict:
    """Read documents again for medicines (background). Found ones are suggestions until you confirm them."""
    return {"queued": jobs.enqueue_meds_rebuild(db)}
