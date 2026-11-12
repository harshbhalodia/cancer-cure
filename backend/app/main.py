from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.routers import api, case_api, jobs_api, plan_api, record, wellness_api
from app.services import casefile, jobs


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    casefile.migrate_legacy()
    with SessionLocal() as db:
        casefile.tidy_events(db)
    if get_settings().worker_enabled:
        jobs.cleanup_staging()
        jobs.start()
    yield
    jobs.stop()


app = FastAPI(title="Cancer-Cure Companion", version="0.1.0", lifespan=lifespan)
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
