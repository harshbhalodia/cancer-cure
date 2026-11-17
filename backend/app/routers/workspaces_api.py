from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.services import workspaces

router = APIRouter(prefix="/api/workspaces")


class WorkspaceIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=120)


@router.get("")
def list_workspaces() -> list[dict]:
    return workspaces.list_workspaces()


@router.post("", status_code=201)
def create_workspace(body: WorkspaceIn) -> dict:
    return workspaces.create(body.label)
