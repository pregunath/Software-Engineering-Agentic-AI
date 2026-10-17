from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


DEFAULT_IGNORED_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".next",
    "dist",
    "build",
    "coverage",
}
DEFAULT_IGNORED_FILES = {".env", ".env.local", ".env.production", ".env.development"}


class InspectionError(ValueError):
    pass


@dataclass(frozen=True)
class InspectionLimits:
    max_file_bytes: int = 256_000
    max_output_chars: int = 50_000
    max_results: int = 200


class RepositoryInspector:
    def __init__(self, root: Path, limits: InspectionLimits | None = None) -> None:
        self.root = root.expanduser().resolve()
        self.limits = limits or InspectionLimits()
        if not self.root.is_dir():
            raise InspectionError("Workspace must be an existing directory")

    def _safe_path(self, relative_path: str = "") -> Path:
        raw_candidate = self.root / relative_path
        if raw_candidate != self.root and self._contains_symlink(raw_candidate):
            raise InspectionError("Symbolic links are not allowed in the workspace")
        candidate = raw_candidate.resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise InspectionError("Path escapes the workspace") from error
        return candidate

    def _contains_symlink(self, path: Path) -> bool:
        current = path
        while current != self.root:
            if current.is_symlink():
                return True
            current = current.parent
        return path.is_symlink()

    def _ignored(self, path: Path) -> bool:
        relative = path.relative_to(self.root)
        parts = relative.parts
        if any(part in DEFAULT_IGNORED_NAMES for part in parts[:-1]):
            return True
        if path.name in DEFAULT_IGNORED_FILES:
            return True
        if fnmatch.fnmatch(path.name, "*.env*"):
            return True
        return any(fnmatch.fnmatch(str(relative), pattern) for pattern in self._ignore_patterns())

    def _ignore_patterns(self) -> list[str]:
        ignore_file = self.root / ".gitignore"
        if not ignore_file.is_file():
            return []
        patterns: list[str] = []
        for line in ignore_file.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("!"):
                patterns.append(stripped.lstrip("/"))
        return patterns

    def list_files(self, relative_path: str = "") -> list[str]:
        directory = self._safe_path(relative_path)
        if not directory.is_dir():
            raise InspectionError("Requested path is not a directory")
        files: list[str] = []
        for current_root, directory_names, file_names in os.walk(directory, topdown=True, followlinks=False):
            current = Path(current_root)
            directory_names[:] = [
                name for name in directory_names
                if not self._ignored(current / name) and not (current / name).is_symlink()
            ]
            for name in sorted(file_names):
                file_path = current / name
                if file_path.is_symlink() or self._ignored(file_path):
                    continue
                files.append(str(file_path.relative_to(self.root)).replace("\\", "/"))
                if len(files) >= self.limits.max_results:
                    return files
        return files

    def read_file(self, relative_path: str) -> str:
        file_path = self._safe_path(relative_path)
        if not file_path.is_file() or self._ignored(file_path):
            raise InspectionError("File is unavailable for inspection")
        if file_path.stat().st_size > self.limits.max_file_bytes:
            raise InspectionError("File exceeds the inspection size limit")
        return file_path.read_text(encoding="utf-8", errors="replace")

    def search_code(self, query: str) -> list[dict[str, object]]:
        if not query.strip():
            raise InspectionError("Search query cannot be empty")
        results: list[dict[str, object]] = []
        for relative_path in self.list_files():
            file_path = self.root / relative_path
            try:
                content = self.read_file(relative_path)
            except (InspectionError, UnicodeError):
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if query.casefold() in line.casefold():
                    results.append({"path": relative_path, "line": line_number, "text": line[:500]})
                    if len(results) >= self.limits.max_results:
                        return results
        return results

    def inspect_project_configuration(self) -> dict[str, str]:
        configuration_files = {
            "pyproject.toml", "package.json", "tsconfig.json", "requirements.txt",
            "poetry.lock", "uv.lock", "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
        }
        available: dict[str, str] = {}
        for name in sorted(configuration_files):
            try:
                available[name] = self.read_file(name)[: self.limits.max_output_chars]
            except InspectionError:
                continue
        return available

    def inspect_git(self, *arguments: str) -> str:
        if not (self.root / ".git").exists():
            raise InspectionError("Workspace is not a Git repository")
        completed = subprocess.run(
            ["git", *arguments], cwd=self.root, capture_output=True, text=True,
            timeout=10, check=False,
        )
        output = (completed.stdout + completed.stderr).strip()
        return output[: self.limits.max_output_chars]

    def git_status(self) -> str:
        return self.inspect_git("status", "--short")

    def git_diff(self) -> str:
        return self.inspect_git("diff", "--no-ext-diff", "--", ".")
