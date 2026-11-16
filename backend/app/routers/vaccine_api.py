from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import cohort, fasttrack, jobs, options, vaccine
from app.vaccine import ingest

router = APIRouter(prefix="/api/vaccine")


@router.get("")
def get_workbench(db: Session = Depends(get_db)) -> dict:
    return vaccine.workbench(db)


@router.get("/options")
def get_options(db: Session = Depends(get_db)) -> dict:
    """Treatment options to discuss with the oncologist (education and questions; not a ranking, not from synthetic data)."""
    return options.view(db)


class CohortIn(BaseModel):
    n: int = 10000
    workers: int = 10


@router.get("/cohort")
def get_cohort(db: Session = Depends(get_db)) -> dict:
    return cohort.view(db)


@router.post("/cohort/start")
def start_cohort(body: CohortIn, db: Session = Depends(get_db)) -> dict:
    try:
        return cohort.start(db, body.n, body.workers)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/cohort/stop")
def stop_cohort() -> dict:
    return cohort.stop()


class AuditIn(BaseModel):
    n: int = 60
    parallel: int = 2


@router.post("/cohort/audit")
def start_audit(body: AuditIn) -> dict:
    """The local model reviews simulated shortlists and is scored against the known answers (background process)."""
    try:
        return cohort.start_audit(body.n, body.parallel)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/fasttrack")
def get_fasttrack(db: Session = Depends(get_db)) -> dict:
    """The fastest route when time is short: parallel steps and ready-to-send drafts built from the records."""
    return fasttrack.view(db)


class TextIn(BaseModel):
    text: str
    dataset: str = "patient"
    source: str = "pasted by you"


def _dataset(name: str) -> str:
    if name not in vaccine.DATASETS:
        raise HTTPException(422, "dataset must be patient or synthetic.")
    return name


@router.post("/variants")
def add_variants(body: TextIn, db: Session = Depends(get_db)) -> dict:
    """Add tumour mutations from a pasted table or VCF. Rows that cannot be read are listed, never guessed."""
    rows, problems = ingest.parse_variants(body.text)
    added = vaccine.add_variants(db, _dataset(body.dataset), rows, body.source) if rows else 0
    return {"read": len(rows), "added": added, "problems": problems[:20]}


@router.post("/hla")
def set_hla(body: TextIn, db: Session = Depends(get_db)) -> dict:
    alleles, problems = ingest.parse_hla(body.text)
    if alleles:
        vaccine.set_hla(db, _dataset(body.dataset), alleles, body.source)
    return {"alleles": alleles, "problems": problems}


@router.post("/hla/from-case")
def hla_from_case(db: Session = Depends(get_db)) -> dict:
    alleles, problems = vaccine.hla_from_case(db)
    if alleles:
        vaccine.set_hla(db, "patient", alleles, "case file")
    return {"alleles": alleles, "problems": problems}


@router.delete("/data", status_code=204)
def clear_data(dataset: str, db: Session = Depends(get_db)) -> None:
    vaccine.clear(db, _dataset(dataset))


@router.post("/synthetic")
def load_synthetic(db: Session = Depends(get_db)) -> dict:
    """Load a clearly labelled synthetic tumour so the pipeline and evals can be tried without any patient data."""
    return vaccine.load_synthetic(db)


class DatasetIn(BaseModel):
    dataset: str = "patient"
    params: dict | None = None


@router.post("/references/fetch")
def fetch_references(body: DatasetIn, db: Session = Depends(get_db)) -> dict:
    """Look up reference proteins. Only gene symbols are sent, to uniprot.org. Never automatic."""
    return vaccine.fetch_references(db, _dataset(body.dataset))


@router.post("/run")
def run_pipeline(body: DatasetIn, db: Session = Depends(get_db)) -> dict:
    if jobs.enqueue_vaccine(db, _dataset(body.dataset), body.params) is None:
        raise HTTPException(409, "A run for this dataset is already in progress.")
    return {"queued": True}


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(vaccine.VaccineRun, run_id)
    if row is None:
        raise HTTPException(404, "Not found.")
    return vaccine.summary(row)


@router.post("/runs/{run_id}/verify")
def verify_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        return vaccine.verify(db, run_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None


@router.get("/runs/{run_id}/dossier", response_class=PlainTextResponse)
def get_dossier(run_id: int, fmt: str = "md", db: Session = Depends(get_db)) -> PlainTextResponse:
    try:
        text = vaccine.dossier_text(db, run_id, "json" if fmt == "json" else "md")
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    media = "application/json" if fmt == "json" else "text/markdown"
    return PlainTextResponse(text, media_type=media, headers={"Content-Disposition": f'attachment; filename="candidate-dossier-{run_id}.{fmt}"'})


class EvalIn(BaseModel):
    board: bool = False


@router.post("/evals")
def run_evals(body: EvalIn | None = None, db: Session = Depends(get_db)) -> dict:
    """Run the pipeline evals in the background; `board` also tests the local-model memo (several minutes)."""
    if jobs.enqueue_vaccine(db, "synthetic", {"board": bool(body and body.board)}, kind="vaccine_eval") is None:
        raise HTTPException(409, "The evals are already running.")
    return {"queued": True}
