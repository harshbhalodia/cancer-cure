from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import consult, priorities

router = APIRouter(prefix="/api/consult")


@router.get("")
def get_consult(db: Session = Depends(get_db)) -> dict:
    priorities.sync(db)
    return consult.view(db)


@router.get("/text")
def get_text(db: Session = Depends(get_db)) -> dict:
    return {"text": consult.checklist_text(db)}


class ItemIn(BaseModel):
    asked: bool | None = None
    answer: str | None = None


@router.put("/items/{key}")
def put_item(key: str, body: ItemIn, db: Session = Depends(get_db)) -> dict:
    consult.set_item(db, key, body.asked, body.answer)
    return {"ok": True}


class AdviceIn(BaseModel):
    advice: str


@router.put("/advice")
def put_advice(body: AdviceIn, db: Session = Depends(get_db)) -> dict:
    consult.set_advice(db, body.advice)
    return {"ok": True}


@router.post("/finish")
def finish_visit(db: Session = Depends(get_db)) -> dict:
    try:
        return consult.finish(db)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
