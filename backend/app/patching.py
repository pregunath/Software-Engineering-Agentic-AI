from __future__ import annotations

import shutil
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.repository_inspection import InspectionError, RepositoryInspector


class PatchError(ValueError):
    pass


@dataclass(frozen=True)
class FileChange:
    path: str
    expected_content: str | None
    new_content: str


@dataclass(frozen=True)
class Checkpoint:
    id: str
    root: Path
    files: tuple[str, ...]


class WorkspaceEditor:
    def __init__(self, root: Path, max_files: int = 20) -> None:
        self.root = root.expanduser().resolve()
        self.max_files = max_files
        self.inspector = RepositoryInspector(self.root)
        self.checkpoint_root = self.root / ".agent-checkpoints"
        self.checkpoint_root.mkdir(exist_ok=True)

    def create_checkpoint(self, paths: list[str]) -> Checkpoint:
        if not paths or len(paths) > self.max_files:
            raise PatchError(f"Checkpoint must contain between 1 and {self.max_files} files")
        checkpoint_id = f"{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"
        destination = self.checkpoint_root / checkpoint_id
        destination.mkdir()
        for relative_path in paths:
            try:
                source = self.inspector._safe_path(relative_path)
            except InspectionError as error:
                raise PatchError(str(error)) from error
            if not source.is_file():
                raise PatchError(f"Cannot checkpoint missing file: {relative_path}")
            target = destination / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return Checkpoint(checkpoint_id, destination, tuple(paths))

    def apply_changes(self, changes: list[FileChange]) -> Checkpoint:
        if not changes or len(changes) > self.max_files:
            raise PatchError(f"Change set must contain between 1 and {self.max_files} files")
        paths = [change.path for change in changes]
        if len(set(paths)) != len(paths):
            raise PatchError("Change set contains duplicate paths")
        checkpoint = self.create_checkpoint(paths)
        try:
            for change in changes:
                target = self.inspector._safe_path(change.path)
                current = target.read_text(encoding="utf-8", errors="replace")
                if change.expected_content is not None and current != change.expected_content:
                    raise PatchError(f"File changed since inspection: {change.path}")
                target.write_text(change.new_content, encoding="utf-8")
        except (OSError, InspectionError, PatchError):
            self.rollback(checkpoint)
            raise
        return checkpoint

    def apply_unified_diff(self, unified_diff: str) -> Checkpoint:
        changes = self._parse_unified_diff(unified_diff)
        return self.apply_changes(changes)

    def _parse_unified_diff(self, unified_diff: str) -> list[FileChange]:
        lines = unified_diff.splitlines(keepends=True)
        changes: list[FileChange] = []
        index = 0
        while index < len(lines):
            if not lines[index].startswith("--- "):
                index += 1
                continue
            old_path = lines[index][4:].rstrip("\r\n").split("\t", 1)[0]
            index += 1
            if index >= len(lines) or not lines[index].startswith("+++ "):
                raise PatchError("Unified diff is missing its new-file header")
            new_path = lines[index][4:].rstrip("\r\n").split("\t", 1)[0]
            if old_path == "/dev/null" or new_path == "/dev/null":
                raise PatchError("File creation and deletion patches are not supported")
            if not old_path.startswith("a/") or not new_path.startswith("b/"):
                raise PatchError("Unified diff paths must use a/ and b/ prefixes")
            relative_path = new_path[2:]
            if old_path[2:] != relative_path:
                raise PatchError("Renames are not supported by the patch tool")
            index += 1
            try:
                original = self.inspector.read_file(relative_path).splitlines(keepends=True)
            except InspectionError as error:
                raise PatchError(str(error)) from error
            patched = list(original)
            offset = 0
            saw_hunk = False
            while index < len(lines) and not lines[index].startswith("--- "):
                if not lines[index].startswith("@@ "):
                    index += 1
                    continue
                saw_hunk = True
                match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[index])
                if not match:
                    raise PatchError("Unified diff contains an invalid hunk header")
                old_start = int(match.group(1)) - 1
                old_count = int(match.group(2) or "1")
                index += 1
                old_segment: list[str] = []
                new_segment: list[str] = []
                while index < len(lines) and not lines[index].startswith(("@@ ", "--- ")):
                    line = lines[index]
                    index += 1
                    if line.startswith("\\ No newline"):
                        continue
                    if not line or line[0] not in " +-":
                        raise PatchError("Unified diff contains an invalid hunk line")
                    if line[0] in " -":
                        old_segment.append(line[1:])
                    if line[0] in " +":
                        new_segment.append(line[1:])
                if len(old_segment) != old_count:
                    raise PatchError("Unified diff hunk does not match its old-line count")
                actual_start = old_start + offset
                if patched[actual_start:actual_start + old_count] != old_segment:
                    raise PatchError(f"Unified diff does not match current file: {relative_path}")
                patched[actual_start:actual_start + old_count] = new_segment
                offset += len(new_segment) - old_count
            if not saw_hunk:
                raise PatchError("Unified diff contains no hunks")
            changes.append(FileChange(relative_path, "".join(original), "".join(patched)))
        if not changes:
            raise PatchError("Unified diff contains no file changes")
        return changes

    def rollback(self, checkpoint: Checkpoint) -> None:
        if checkpoint.root.parent != self.checkpoint_root:
            raise PatchError("Checkpoint does not belong to this workspace")
        for relative_path in checkpoint.files:
            source = checkpoint.root / relative_path
            target = self.inspector._safe_path(relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
