from __future__ import annotations

from contextlib import contextmanager
import uuid

from app.config import get_base_settings, settings_context
from app.database import SessionLocal, catalog_session, current_engine
from app.models import Case, Workspace


def list_workspaces() -> list[dict]:
    with catalog_session() as db:
        return [{"id": "primary", "label": "Existing patient"}] + [
            {"id": row.id, "label": row.label}
            for row in db.query(Workspace).order_by(Workspace.created_at, Workspace.id)
        ]


@contextmanager
def activate(workspace_id: str):
    settings = get_base_settings()
    if workspace_id != "primary":
        with catalog_session() as db:
            if db.get(Workspace, workspace_id) is None:
                raise ValueError("Patient workspace not found. Select an existing patient.")
        directory = settings.data_dir / "patients" / workspace_id
        settings = settings.model_copy(update={"data_dir": directory, "inbox_dir": directory / "inbox"})
    with settings_context(settings):
        yield


def create(label: str) -> dict:
    workspace_id = uuid.uuid4().hex
    base = get_base_settings()
    directory = base.data_dir / "patients" / workspace_id
    settings = base.model_copy(update={"data_dir": directory, "inbox_dir": directory / "inbox"})
    with settings_context(settings):
        current_engine()
        with SessionLocal() as db:
            db.add(Case(id=1))
            db.commit()
    with catalog_session() as db:
        db.add(Workspace(id=workspace_id, label=label))
        db.commit()
    return {"id": workspace_id, "label": label}
