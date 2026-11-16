from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Trial
from app.services import trials

router = APIRouter(prefix="/api/trials")


class NctIn(BaseModel):
    nct_id: str


class TextIn(BaseModel):
    text: str


def _row(db: Session, trial_id: int) -> Trial:
    row = db.get(Trial, trial_id)
    if row is None:
        raise HTTPException(404, "Trial not found.")
    return row


@router.get("")
def list_trials(db: Session = Depends(get_db)) -> list[dict]:
    out = []
    for t in db.query(Trial).order_by(Trial.id):
        a = trials.assess(db, t)
        out.append({k: a[k] for k in ("id", "nct_id", "title", "status", "counts", "fetched_at")})
    return out


@router.get("/search")
def search(term: str = "vaccine OR neoantigen", country: str = "") -> list[dict]:
    """Search ClinicalTrials.gov. Only these generic words leave the computer."""
    try:
        return trials.search(term, country)
    except trials.TrialError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("")
def add_trial(body: NctIn, db: Session = Depends(get_db)) -> dict:
    try:
        return trials.assess(db, trials.add(db, body.nct_id))
    except trials.TrialError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/{trial_id}")
def get_trial(trial_id: int, db: Session = Depends(get_db)) -> dict:
    return trials.assess(db, _row(db, trial_id))


@router.put("/{trial_id}/profile")
def put_profile(trial_id: int, body: dict, db: Session = Depends(get_db)) -> dict:
    row = _row(db, trial_id)
    trials.set_profile(db, row, body)
    return trials.assess(db, row)


@router.post("/{trial_id}/refresh")
def refresh(trial_id: int, db: Session = Depends(get_db)) -> dict:
    row = _row(db, trial_id)
    try:
        trials.refresh(db, row)
    except trials.TrialError as exc:
        raise HTTPException(502, str(exc)) from exc
    return trials.assess(db, row)


@router.post("/{trial_id}/log")
def log(trial_id: int, body: TextIn, db: Session = Depends(get_db)) -> dict:
    row = _row(db, trial_id)
    trials.add_log(db, row, body.text)
    return trials.assess(db, row)


@router.delete("/{trial_id}", status_code=204)
def delete(trial_id: int, db: Session = Depends(get_db)) -> None:
    db.delete(_row(db, trial_id))
    db.commit()
