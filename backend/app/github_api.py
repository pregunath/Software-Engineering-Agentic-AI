from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.events import record_event
from app.models import ConnectedGithubRepo, RegisteredWorkspace, Task, TaskStatus, User
from app.security import seal_secret, unseal_secret
from app.user_auth import get_current_user

router = APIRouter(prefix="/github", tags=["github"])


class GithubConnectRequest(BaseModel):
    personal_access_token: str = Field(min_length=8, max_length=200)


class GithubStatus(BaseModel):
    connected: bool
    login: str | None


class GithubRemoteRepo(BaseModel):
    full_name: str
    description: str | None
    private: bool
    default_branch: str
    clone_url: str
    html_url: str


class ConnectRepoRequest(BaseModel):
    full_name: str = Field(min_length=3, max_length=300)


class ConnectedRepoRead(BaseModel):
    id: int
    full_name: str
    default_branch: str
    local_path: str | None
    workspace_id: int | None


class AgentTaskRequest(BaseModel):
    repo_id: int
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20_000)


def _token_for(user: User, settings: Settings) -> str:
    if not user.github_token_sealed:
        raise HTTPException(status_code=400, detail="Connect GitHub first")
    try:
        return unseal_secret(user.github_token_sealed, settings)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Stored GitHub token is invalid") from error


async def _github_get(path: str, token: str, settings: Settings) -> object:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Forge-Agent",
    }
    try:
        async with httpx.AsyncClient(base_url=settings.github_api_base_url, timeout=30.0) as client:
            response = await client.get(path, headers=headers)
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=f"GitHub request failed: {error}") from error
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="GitHub rejected the token")
    if response.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"GitHub error: {response.text[:300]}")
    return response.json()


@router.get("/status", response_model=GithubStatus)
def github_status(user: User = Depends(get_current_user)) -> GithubStatus:
    return GithubStatus(connected=bool(user.github_token_sealed), login=user.github_login)


@router.post("/connect", response_model=GithubStatus)
async def connect_github(
    request: GithubConnectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GithubStatus:
    token = request.personal_access_token.strip()
    profile = await _github_get("/user", token, settings)
    if not isinstance(profile, dict) or not isinstance(profile.get("login"), str):
        raise HTTPException(status_code=400, detail="Unexpected GitHub profile response")
    user.github_token_sealed = seal_secret(token, settings)
    user.github_login = profile["login"]
    db.commit()
    db.refresh(user)
    return GithubStatus(connected=True, login=user.github_login)


@router.delete("/connect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_github(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    user.github_token_sealed = None
    user.github_login = None
    db.commit()


@router.get("/repos", response_model=list[GithubRemoteRepo])
async def list_remote_repos(
    user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)
) -> list[GithubRemoteRepo]:
    token = _token_for(user, settings)
    payload = await _github_get("/user/repos?per_page=100&sort=updated", token, settings)
    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="Unexpected GitHub repos response")
    repos: list[GithubRemoteRepo] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        repos.append(
            GithubRemoteRepo(
                full_name=str(item.get("full_name") or ""),
                description=item.get("description") if isinstance(item.get("description"), str) else None,
                private=bool(item.get("private")),
                default_branch=str(item.get("default_branch") or "main"),
                clone_url=str(item.get("clone_url") or ""),
                html_url=str(item.get("html_url") or ""),
            )
        )
    return [repo for repo in repos if repo.full_name and repo.clone_url]


@router.get("/connected", response_model=list[ConnectedRepoRead])
def list_connected(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ConnectedRepoRead]:
    rows = db.scalars(
        select(ConnectedGithubRepo)
        .where(ConnectedGithubRepo.user_id == user.id)
        .order_by(ConnectedGithubRepo.created_at.desc())
    ).all()
    return [
        ConnectedRepoRead(
            id=row.id,
            full_name=row.full_name,
            default_branch=row.default_branch,
            local_path=row.local_path,
            workspace_id=row.workspace_id,
        )
        for row in rows
    ]


def _clone_repo(clone_url: str, token: str, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Prefer HTTPS with token without writing the token into logs.
    auth_url = clone_url.replace("https://", f"https://x-access-token:{token}@", 1)
    completed = subprocess.run(
        ["git", "clone", "--depth", "1", auth_url, str(destination)],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "git clone failed").replace(token, "***")
        raise HTTPException(status_code=400, detail=detail[:500])


@router.post("/connected", response_model=ConnectedRepoRead, status_code=status.HTTP_201_CREATED)
async def connect_repo(
    request: ConnectRepoRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ConnectedRepoRead:
    token = _token_for(user, settings)
    full_name = request.full_name.strip()
    remote = await _github_get(f"/repos/{full_name}", token, settings)
    if not isinstance(remote, dict):
        raise HTTPException(status_code=404, detail="Repository not found on GitHub")

    existing = db.scalars(
        select(ConnectedGithubRepo).where(
            ConnectedGithubRepo.user_id == user.id, ConnectedGithubRepo.full_name == full_name
        )
    ).first()

    safe_name = full_name.replace("/", "__")
    destination = Path(".workspaces") / "github" / str(user.id) / safe_name
    _clone_repo(str(remote.get("clone_url") or ""), token, destination)

    workspace = db.scalars(
        select(RegisteredWorkspace).where(RegisteredWorkspace.root_path == str(destination.resolve()))
    ).first()
    if workspace is None:
        workspace = RegisteredWorkspace(name=full_name, root_path=str(destination.resolve()))
        db.add(workspace)
        db.flush()

    if existing is None:
        existing = ConnectedGithubRepo(
            user_id=user.id,
            full_name=full_name,
            clone_url=str(remote.get("clone_url") or ""),
            default_branch=str(remote.get("default_branch") or "main"),
            local_path=str(destination.resolve()),
            workspace_id=workspace.id,
        )
        db.add(existing)
    else:
        existing.clone_url = str(remote.get("clone_url") or "")
        existing.default_branch = str(remote.get("default_branch") or "main")
        existing.local_path = str(destination.resolve())
        existing.workspace_id = workspace.id

    db.commit()
    db.refresh(existing)
    return ConnectedRepoRead(
        id=existing.id,
        full_name=existing.full_name,
        default_branch=existing.default_branch,
        local_path=existing.local_path,
        workspace_id=existing.workspace_id,
    )


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_agent_task(
    request: AgentTaskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    repo = db.get(ConnectedGithubRepo, request.repo_id)
    if repo is None or repo.user_id != user.id:
        raise HTTPException(status_code=404, detail="Connected repository not found")
    if not repo.local_path or not repo.workspace_id:
        raise HTTPException(status_code=400, detail="Repository is not cloned locally yet")

    task = Task(
        title=request.title.strip(),
        description=request.description.strip(),
        status=TaskStatus.QUEUED.value,
        workspace_id=repo.workspace_id,
        user_id=user.id,
        github_repo_id=repo.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    record_event(
        db,
        task.id,
        "task.created",
        {"status": task.status, "title": task.title, "github_repo": repo.full_name},
    )
    db.commit()
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "workspace_id": task.workspace_id,
        "github_repo_id": task.github_repo_id,
        "local_path": repo.local_path,
    }
