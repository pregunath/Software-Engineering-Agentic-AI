"""Local host workspace registry and sandboxed file operations."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import RegisteredWorkspace
from app.patching import FileChange, PatchError, WorkspaceEditor
from app.repository_inspection import InspectionError, RepositoryInspector
from app.workspace import WorkspaceError, WorkspaceManager

router = APIRouter(prefix="/repos", tags=["repos"])


class RepoRegister(BaseModel):
    path: str = Field(min_length=1, max_length=1_000)
    name: str | None = Field(default=None, max_length=200)


class RepoRead(BaseModel):
    id: int
    name: str
    root_path: str
    agent_workspace_path: str | None
    host_workspaces_enabled: bool


class FileWriteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=500_000)
    expected_content: str | None = Field(default=None, max_length=500_000)


class FileSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


def _require_host_workspaces(settings: Settings) -> None:
    if not settings.allow_host_workspaces:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Host workspace registration is disabled on this server. "
                "Set AGENT_ALLOW_HOST_WORKSPACES=true only on trusted local API hosts."
            ),
        )


def _get_repo(db: Session, repo_id: int) -> RegisteredWorkspace:
    repo = db.get(RegisteredWorkspace, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


def _inspector(repo: RegisteredWorkspace) -> RepositoryInspector:
    try:
        return RepositoryInspector(Path(repo.root_path))
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _build_tree(files: list[str]) -> list[dict[str, object]]:
    root: dict[str, object] = {"name": "", "path": "", "type": "directory", "children": {}}
    for relative in files:
        parts = relative.split("/")
        node = root
        for index, part in enumerate(parts):
            children: dict[str, object] = node["children"]  # type: ignore[assignment]
            if part not in children:
                is_file = index == len(parts) - 1
                children[part] = {
                    "name": part,
                    "path": "/".join(parts[: index + 1]),
                    "type": "file" if is_file else "directory",
                    "children": {} if not is_file else None,
                }
            node = children[part]  # type: ignore[assignment]

    def to_list(directory: dict[str, object]) -> list[dict[str, object]]:
        children = directory.get("children") or {}
        assert isinstance(children, dict)
        entries: list[dict[str, object]] = []
        for child in children.values():
            assert isinstance(child, dict)
            if child["type"] == "directory":
                entries.append(
                    {
                        "name": child["name"],
                        "path": child["path"],
                        "type": "directory",
                        "children": to_list(child),
                    }
                )
            else:
                entries.append({"name": child["name"], "path": child["path"], "type": "file"})
        entries.sort(key=lambda item: (0 if item["type"] == "directory" else 1, str(item["name"]).lower()))
        return entries

    return to_list(root)


@router.get("/capabilities")
def repo_capabilities(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    return {
        "host_workspaces_enabled": settings.allow_host_workspaces,
        "mode": "local_host_paths" if settings.allow_host_workspaces else "disabled",
        "note": (
            "Register an absolute path on the machine running the Forge API. "
            "A browser cannot browse arbitrary folders on your computer."
        ),
    }


@router.get("", response_model=list[RepoRead])
def list_repos(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> list[RepoRead]:
    rows = list(db.scalars(select(RegisteredWorkspace).order_by(RegisteredWorkspace.created_at.desc())).all())
    return [
        RepoRead(
            id=row.id,
            name=row.name,
            root_path=row.root_path,
            agent_workspace_path=row.agent_workspace_path,
            host_workspaces_enabled=settings.allow_host_workspaces,
        )
        for row in rows
    ]


@router.post("", response_model=RepoRead, status_code=status.HTTP_201_CREATED)
def register_repo(
    request: RepoRegister,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RepoRead:
    _require_host_workspaces(settings)
    root = Path(request.path).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail="Path must be an existing directory on the API host")
    existing = db.scalars(select(RegisteredWorkspace).where(RegisteredWorkspace.root_path == str(root))).first()
    if existing is not None:
        return RepoRead(
            id=existing.id,
            name=existing.name,
            root_path=existing.root_path,
            agent_workspace_path=existing.agent_workspace_path,
            host_workspaces_enabled=settings.allow_host_workspaces,
        )
    name = (request.name or root.name).strip() or root.name
    row = RegisteredWorkspace(name=name, root_path=str(root))
    db.add(row)
    db.commit()
    db.refresh(row)
    return RepoRead(
        id=row.id,
        name=row.name,
        root_path=row.root_path,
        agent_workspace_path=row.agent_workspace_path,
        host_workspaces_enabled=settings.allow_host_workspaces,
    )


@router.get("/{repo_id}", response_model=RepoRead)
def get_repo(
    repo_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> RepoRead:
    row = _get_repo(db, repo_id)
    return RepoRead(
        id=row.id,
        name=row.name,
        root_path=row.root_path,
        agent_workspace_path=row.agent_workspace_path,
        host_workspaces_enabled=settings.allow_host_workspaces,
    )


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_repo(repo_id: int, db: Session = Depends(get_db)) -> None:
    row = _get_repo(db, repo_id)
    db.delete(row)
    db.commit()


@router.get("/{repo_id}/tree")
def repo_tree(repo_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    inspector = _inspector(_get_repo(db, repo_id))
    try:
        files = inspector.list_files()
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"files": files, "tree": _build_tree(files)}


@router.get("/{repo_id}/file")
def read_repo_file(repo_id: int, path: str, db: Session = Depends(get_db)) -> dict[str, str]:
    inspector = _inspector(_get_repo(db, repo_id))
    try:
        content = inspector.read_file(path)
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"path": path, "content": content}


@router.put("/{repo_id}/file")
def write_repo_file(repo_id: int, request: FileWriteRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    repo = _get_repo(db, repo_id)
    editor = WorkspaceEditor(Path(repo.root_path))
    try:
        # Creating brand-new files is not supported by WorkspaceEditor checkpoints;
        # only overwrite existing sandboxed files with optimistic concurrency.
        inspector = editor.inspector
        target = inspector._safe_path(request.path)
        if not target.is_file() or inspector._ignored(target):
            raise HTTPException(status_code=400, detail="File is unavailable for editing")
        checkpoint = editor.apply_changes(
            [FileChange(path=request.path, expected_content=request.expected_content, new_content=request.content)]
        )
    except PatchError as error:
        detail = str(error)
        code = 409 if "changed since inspection" in detail else 400
        raise HTTPException(status_code=code, detail=detail) from error
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"path": request.path, "checkpoint_id": checkpoint.id, "saved": True}


@router.post("/{repo_id}/search")
def search_repo(repo_id: int, request: FileSearchRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    inspector = _inspector(_get_repo(db, repo_id))
    try:
        return {"results": inspector.search_code(request.query)}
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/{repo_id}/git/status")
def repo_git_status(repo_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    inspector = _inspector(_get_repo(db, repo_id))
    try:
        branch = inspector.inspect_git("rev-parse", "--abbrev-ref", "HEAD")
        status_output = inspector.git_status()
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"branch": branch, "status": status_output}


@router.get("/{repo_id}/git/diff")
def repo_git_diff(repo_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    inspector = _inspector(_get_repo(db, repo_id))
    try:
        return {"diff": inspector.git_diff()}
    except InspectionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/{repo_id}/agent-workspace")
def create_agent_workspace(repo_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    """Create/refresh a disposable copy used for agent patch + test execution."""
    repo = _get_repo(db, repo_id)
    try:
        workspace = WorkspaceManager(Path(".workspaces")).create_copy(Path(repo.root_path))
    except (OSError, WorkspaceError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    repo.agent_workspace_path = str(workspace.path)
    db.commit()
    db.refresh(repo)
    return {"source": str(workspace.source), "path": str(workspace.path)}
