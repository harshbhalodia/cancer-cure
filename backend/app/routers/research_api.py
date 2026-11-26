from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, Job, VaccineRun
from app.research_models import ResearchEvidence, ResearchExperiment, ResearchLoop, ResearchSource
from app.services import research, research_loops, research_notebook

router = APIRouter(prefix="/api/research")


class NotebookSourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: StrictStr = Field(min_length=1, max_length=200)
    kind: Literal["correspondence", "publication", "registry", "personal_note"]
    text: StrictStr = Field(min_length=20, max_length=12000)
    source_url: StrictStr = Field(default="", max_length=2000)
    as_of: StrictStr

    @field_validator("source_url")
    @classmethod
    def valid_optional_url(cls, value: str) -> str:
        return research.validate_source_url(value) if value else ""

    @field_validator("as_of")
    @classmethod
    def valid_source_date(cls, value: str) -> str:
        return research.validate_as_of(value)


class NotebookBriefIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: StrictStr = Field(min_length=10, max_length=2000)
    source_ids: list[StrictInt] = Field(min_length=1, max_length=8)


@router.get("/notebook")
def get_notebook(db: Session = Depends(get_db)) -> dict:
    sources = db.query(ResearchSource).order_by(ResearchSource.id.desc()).all()
    briefs = db.query(Job).filter_by(kind="research_brief").order_by(Job.id.desc()).limit(20).all()
    return {
        "sources": [research_notebook.source_dict(row) for row in sources],
        "briefs": [research_notebook.brief_dict(job) for job in briefs],
        "disclaimer": research_notebook.DISCLAIMER,
        "loops": [research_loops.loop_dict(db, row) for row in db.query(ResearchLoop).order_by(ResearchLoop.id.desc()).limit(10)],
    }


@router.post("/notebook/sources", status_code=201)
def add_notebook_source(body: NotebookSourceIn, db: Session = Depends(get_db)) -> dict:
    return research_notebook.save_source(db, body.model_dump())


@router.post("/notebook/briefs", status_code=202)
def create_notebook_brief(body: NotebookBriefIn, db: Session = Depends(get_db)) -> dict:
    try:
        job = research_notebook.queue_brief(db, body.question, body.source_ids)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return research_notebook.brief_dict(job)


class CycleApprovalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    previous_job_id: StrictInt = Field(gt=0)


@router.post("/notebook/loops", status_code=202)
def create_research_loop(body: NotebookBriefIn, db: Session = Depends(get_db)) -> dict:
    try:
        loop = research_loops.create_loop(db, body.question, body.source_ids)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except research_loops.LoopConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return research_loops.loop_dict(db, loop)


@router.post("/notebook/loops/{loop_id}/approve", status_code=202)
def approve_research_cycle(loop_id: int, body: CycleApprovalIn, db: Session = Depends(get_db)) -> dict:
    loop = db.get(ResearchLoop, loop_id)
    if loop is None:
        raise HTTPException(404, "Research loop not found in this workspace.")
    try:
        research_loops.approve_next(db, loop, body.previous_job_id)
    except research_loops.LoopConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return research_loops.loop_dict(db, loop)


@router.post("/notebook/loops/{loop_id}/close")
def close_research_loop(loop_id: int, db: Session = Depends(get_db)) -> dict:
    loop = db.get(ResearchLoop, loop_id)
    if loop is None:
        raise HTTPException(404, "Research loop not found in this workspace.")
    research_loops.close_loop(db, loop)
    return research_loops.loop_dict(db, loop)


class EvidenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_url: StrictStr = Field(min_length=1, max_length=2000)
    study_id: StrictStr = Field(default="", max_length=100)
    platform: StrictStr = Field(min_length=1, max_length=200)
    disease: StrictStr = Field(min_length=1, max_length=300)
    setting: Literal["active_recurrent", "postoperative", "other", "unknown"] = "unknown"
    prior_pd1: Literal["yes", "no", "unknown"] = "unknown"
    endpoint_result: StrictStr = Field(min_length=1, max_length=5000)
    n: StrictInt | None = Field(default=None, gt=0, le=2_000_000_000)
    followup: StrictStr = Field(default="", max_length=200)
    evidence_level: Literal["registry", "conference", "peer_reviewed"]
    limitations: StrictStr = Field(default="", max_length=5000)
    as_of: StrictStr

    @field_validator("source_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        try:
            return research.validate_source_url(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("as_of")
    @classmethod
    def valid_date(cls, value: str) -> str:
        try:
            return research.validate_as_of(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    disease: StrictStr = Field(default="", max_length=300)
    setting: Literal["active_recurrent", "postoperative", "other", "unknown"] = "unknown"
    prior_pd1: Literal["yes", "no", "unknown"] = "unknown"


class ExperimentIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_run_id: StrictInt = Field(gt=0)
    hypothesis: StrictStr = Field(min_length=1, max_length=2000)


def _assistant_job(db: Session, kind: str, key: str, ref_id: int, enqueue: bool = False) -> dict | None:
    rows = db.query(Job).filter(Job.kind == kind).order_by(Job.id.desc()).all()
    latest = next((row for row in rows if (row.payload or {}).get(key) == ref_id), None)
    if enqueue:
        if latest and latest.status in {"queued", "running"}:
            raise HTTPException(409, "Local research assistant is already queued or running.")
        latest = Job(kind=kind, filename="Local AI research assistant", payload={key: ref_id})
        db.add(latest)
        db.commit()
    return {"id": latest.id, "kind": latest.kind, "status": latest.status, "error": latest.error, "result": latest.result} if latest else None


@router.get("/runs/{run_id}/hypotheses")
def get_hypotheses(run_id: int, db: Session = Depends(get_db)) -> dict:
    if db.get(VaccineRun, run_id) is None:
        raise HTTPException(404, "Run not found.")
    return {"job": _assistant_job(db, "research_propose", "source_run_id", run_id)}


@router.post("/runs/{run_id}/hypotheses", status_code=202)
def draft_hypotheses(run_id: int, db: Session = Depends(get_db)) -> dict:
    run = db.get(VaccineRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    if run.status != "done":
        raise HTTPException(422, "Choose a completed run.")
    return {"job": _assistant_job(db, "research_propose", "source_run_id", run_id, True)}


@router.get("/experiments/{experiment_id}/review")
def get_review(experiment_id: int, db: Session = Depends(get_db)) -> dict:
    if db.get(ResearchExperiment, experiment_id) is None:
        raise HTTPException(404, "Scenario snapshot not found.")
    return {"job": _assistant_job(db, "research_review", "experiment_id", experiment_id)}


@router.post("/experiments/{experiment_id}/review", status_code=202)
def review_snapshot(experiment_id: int, db: Session = Depends(get_db)) -> dict:
    if db.get(ResearchExperiment, experiment_id) is None:
        raise HTTPException(404, "Scenario snapshot not found.")
    return {"job": _assistant_job(db, "research_review", "experiment_id", experiment_id, True)}


@router.get("/evidence")
def list_evidence(db: Session = Depends(get_db)) -> dict:
    rows = db.query(ResearchEvidence).order_by(ResearchEvidence.id.desc()).all()
    return {
        "items": [
            {**research.evidence_dict(row), "comparison": research.compare_evidence(db, row)}
            for row in rows
        ],
        "note": "User-entered citations are unverified. Confirm source details before relying on them.",
    }


@router.post("/evidence", status_code=201)
def create_evidence(body: EvidenceIn, db: Session = Depends(get_db)) -> dict:
    try:
        values = research.validate_evidence(body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = ResearchEvidence(**values)
    db.add(row)
    db.flush()
    db.add(Event(kind="research", title="Research evidence card added", detail=f"User-entered citation card {row.id}; source not independently verified.", ref_type="research_evidence", ref_id=row.id))
    db.commit()
    db.refresh(row)
    return {**research.evidence_dict(row), "comparison": research.compare_evidence(db, row)}


@router.delete("/evidence/{evidence_id}", status_code=204)
def delete_evidence(evidence_id: int, db: Session = Depends(get_db)) -> Response:
    row = db.get(ResearchEvidence, evidence_id)
    if row is None:
        raise HTTPException(404, "Evidence card not found.")
    db.delete(row)
    db.add(Event(kind="research", title="Research evidence card removed", detail=f"Removed user-entered citation card {evidence_id}.", ref_type="research_evidence", ref_id=evidence_id))
    db.commit()
    return Response(status_code=204)


@router.get("/profile")
def get_profile(db: Session = Depends(get_db)) -> dict:
    return research.profile_dict(db)


@router.put("/profile")
def put_profile(body: ProfileIn, db: Session = Depends(get_db)) -> dict:
    try:
        return research.save_profile(db, body.disease, body.setting, body.prior_pd1)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/experiments")
def list_experiments(db: Session = Depends(get_db)) -> dict:
    rows = db.query(ResearchExperiment).order_by(ResearchExperiment.id.desc()).all()
    return {"items": [research.experiment_dict(row) for row in rows], "computational_only": True}


@router.post("/experiments", status_code=201)
def create_experiment(body: ExperimentIn, db: Session = Depends(get_db)) -> dict:
    try:
        row = research.create_experiment(db, body.source_run_id, body.hypothesis)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return research.experiment_dict(row)


@router.get("/experiments/compare")
def compare_experiment_snapshots(
    left_id: int = Query(gt=0),
    right_id: int = Query(gt=0),
    db: Session = Depends(get_db),
) -> dict:
    left = db.get(ResearchExperiment, left_id)
    right = db.get(ResearchExperiment, right_id)
    if left is None or right is None:
        raise HTTPException(404, "Experiment snapshot not found.")
    return research.compare_experiments(left, right)
