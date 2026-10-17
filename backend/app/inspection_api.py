from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repository_inspection import InspectionError, RepositoryInspector

router = APIRouter(prefix="/inspection", tags=["inspection"])


class WorkspaceRequest(BaseModel):
    workspace_path: str = Field(min_length=1, max_length=1_000)


class FileRequest(WorkspaceRequest):
    path: str = Field(min_length=1, max_length=500)


class SearchRequest(WorkspaceRequest):
    query: str = Field(min_length=1, max_length=500)


def inspector_for(request: WorkspaceRequest) -> RepositoryInspector:
    try:
        return RepositoryInspector(Path(request.workspace_path))
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/files")
def list_files(request: WorkspaceRequest) -> dict[str, list[str]]:
    inspector = inspector_for(request)
    try:
        return {"files": inspector.list_files()}
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/file")
def read_file(request: FileRequest) -> dict[str, str]:
    inspector = inspector_for(request)
    try:
        return {"path": request.path, "content": inspector.read_file(request.path)}
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/search")
def search_code(request: SearchRequest) -> dict[str, list[dict[str, object]]]:
    inspector = inspector_for(request)
    try:
        return {"results": inspector.search_code(request.query)}
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/configuration")
def inspect_configuration(request: WorkspaceRequest) -> dict[str, dict[str, str]]:
    inspector = inspector_for(request)
    return {"files": inspector.inspect_project_configuration()}


@router.post("/git/status")
def git_status(request: WorkspaceRequest) -> dict[str, str]:
    inspector = inspector_for(request)
    try:
        return {"output": inspector.git_status()}
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/git/diff")
def git_diff(request: WorkspaceRequest) -> dict[str, str]:
    inspector = inspector_for(request)
    try:
        return {"output": inspector.git_diff()}
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
