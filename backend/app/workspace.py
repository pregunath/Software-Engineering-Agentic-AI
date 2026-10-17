from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.repository_inspection import DEFAULT_IGNORED_NAMES


class WorkspaceError(ValueError):
    pass


@dataclass(frozen=True)
class Workspace:
    source: Path
    path: Path


class WorkspaceManager:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def create_copy(self, source: Path) -> Workspace:
        source = source.expanduser().resolve()
        if not source.is_dir():
            raise WorkspaceError("Source repository must be an existing directory")
        if source == self.workspace_root or self.workspace_root.is_relative_to(source):
            raise WorkspaceError("Workspace storage cannot be inside the source repository")
        destination = self.workspace_root / source.name
        counter = 1
        while destination.exists():
            destination = self.workspace_root / f"{source.name}-{counter}"
            counter += 1
        shutil.copytree(source, destination, ignore=self._copy_ignore)
        return Workspace(source=source, path=destination)

    @staticmethod
    def _copy_ignore(directory: str, names: list[str]) -> set[str]:
        ignored = set(DEFAULT_IGNORED_NAMES)
        ignored.update({".git", ".env", ".env.local", ".env.production", ".env.development"})
        ignored.update(name for name in names if name.endswith(".env"))
        return {name for name in names if name in ignored}
