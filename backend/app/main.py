from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.routers import api, case_api, consult_api, jobs_api, plan_api, record, trials_api, vaccine_api, watch_api, wellness_api, workspaces_api, actions_api
from app.services import casefile, jobs, priorities, workspaces
from app.routers import research_api


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    casefile.migrate_legacy()
    with SessionLocal() as db:
        casefile.tidy_events(db)
        priorities.sync(db)
    if get_settings().worker_enabled:
        jobs.cleanup_staging()
        jobs.start()
    yield
    jobs.stop()


app = FastAPI(title="Cancer-Cure Companion", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def patient_workspace(request, call_next):
    header = request.headers.get("X-CC-Workspace")
    query = request.query_params.get("workspace")
    if header and query and header != query:
        return JSONResponse({"detail": "Conflicting patient workspace selections."}, status_code=400)
    workspace_id = header or query or "primary"
    # Validate before the handler; never turn handler errors into workspace fallbacks.
    known = {w["id"] for w in workspaces.list_workspaces()}
    if workspace_id not in known:
        return JSONResponse({"detail": "Patient workspace not found."}, status_code=404)
    with workspaces.activate(workspace_id):
        return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api.router)
app.include_router(case_api.router)
app.include_router(record.router)
app.include_router(jobs_api.router)
app.include_router(plan_api.router)
app.include_router(wellness_api.router)
app.include_router(consult_api.router)
app.include_router(watch_api.router)
app.include_router(vaccine_api.router)
app.include_router(trials_api.router)
app.include_router(workspaces_api.router)
app.include_router(actions_api.router)
app.include_router(research_api.router)
