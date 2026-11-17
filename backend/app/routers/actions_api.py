from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CareAction
from app.services import actions

router = APIRouter(prefix="/api/actions")


class ActionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(default="", max_length=300)
    why: str = Field(default="", max_length=2000)
    owner: str = Field(default="You", min_length=1, max_length=120)
    due_date: str = ""
    priority: Literal["urgent", "high", "routine"] = "routine"
    source_key: str | None = Field(default=None, max_length=120)

    @field_validator("due_date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if value and date.fromisoformat(value).isoformat() != value:
            raise ValueError("Use a date in YYYY-MM-DD format.")
        return value


class ActionPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    owner: str | None = Field(default=None, min_length=1, max_length=120)
    due_date: str | None = None
    priority: Literal["urgent", "high", "routine"] | None = None
    status: Literal["open", "contacted", "awaiting_reply", "resolved", "dismissed"] | None = None
    answer: str | None = Field(default=None, max_length=4000)
    answer_source: Literal["you", "clinician", "coordinator"] | None = None

    @field_validator("due_date")
    @classmethod
    def valid_date(cls, value: str | None) -> str | None:
        return ActionIn.valid_date(value) if value is not None else value


@router.get("")
def list_actions(db: Session = Depends(get_db)) -> dict:
    return actions.view(db)


@router.get("/visit-summary")
def visit_summary(db: Session = Depends(get_db)) -> dict:
    return {"text": actions.visit_text(db)}


@router.post("", status_code=201)
def create_action(body: ActionIn, db: Session = Depends(get_db)) -> dict:
    try:
        return actions.as_dict(actions.create(db, body.model_dump()))
    except ValueError as exc:
        raise HTTPException(409 if body.source_key else 422, str(exc)) from exc


@router.patch("/{action_id}")
def update_action(action_id: int, body: ActionPatch, db: Session = Depends(get_db)) -> dict:
    row = db.get(CareAction, action_id)
    if row is None:
        raise HTTPException(404, "Follow-up not found.")
    fields = body.model_dump(exclude_unset=True)
    if any(v is None for v in fields.values()):
        raise HTTPException(422, "Use an empty string to clear a date or answer; null is not accepted.")
    try:
        actions.update(db, row, fields)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return actions.as_dict(row)
