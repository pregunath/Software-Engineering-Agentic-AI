from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.workspace import WorkspaceError, WorkspaceManager

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceCreate(BaseModel):
    source_path: str = Field(min_length=1, max_length=1_000)


@router.post("", status_code=201)
def create_workspace(request: WorkspaceCreate) -> dict[str, str]:
    try:
        workspace = WorkspaceManager(Path(".workspaces")).create_copy(Path(request.source_path))
    except (OSError, WorkspaceError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"source": str(workspace.source), "path": str(workspace.path)}
