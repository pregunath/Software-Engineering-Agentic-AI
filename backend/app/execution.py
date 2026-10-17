from __future__ import annotations

import subprocess
import time
import json
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ExecutionError(ValueError):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    isolated: bool = False


SAFE_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("py", "-m", "pytest"),
    ("npm", "test"),
    ("npm", "run", "lint"),
    ("npm", "run", "build"),
    ("npx", "tsc", "--noEmit"),
)


class SafeCommandRunner:
    def __init__(self, workspace: Path, timeout_seconds: float = 120.0, max_output_chars: int = 50_000) -> None:
        self.workspace = workspace.expanduser().resolve()
        if not self.workspace.is_dir():
            raise ExecutionError("Execution workspace must be an existing directory")
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars

    def _is_allowed(self, command: tuple[str, ...]) -> bool:
        return any(command[: len(allowed)] == allowed for allowed in SAFE_COMMANDS)

    def run(self, command: list[str]) -> CommandResult:
        normalized = tuple(command)
        if not normalized or not self._is_allowed(normalized):
            raise ExecutionError("Command is not on the approved test command allowlist")
        started = time.monotonic()
        try:
            completed = subprocess.run(
                list(normalized), cwd=self.workspace, capture_output=True, text=True,
                timeout=self.timeout_seconds, check=False, shell=False,
            )
            return CommandResult(
                normalized, completed.returncode,
                completed.stdout[: self.max_output_chars],
                completed.stderr[: self.max_output_chars],
                time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as error:
            stdout = (error.stdout or "")[: self.max_output_chars]
            stderr = (error.stderr or "")[: self.max_output_chars]
            return CommandResult(
                normalized, -1, stdout, stderr,
                time.monotonic() - started, timed_out=True,
            )
        except OSError as error:
            raise ExecutionError(f"Approved command could not start: {error}") from error


class DockerIsolationUnavailable(ExecutionError):
    pass


class ProjectTestCommandDetector:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.expanduser().resolve()
        if not self.workspace.is_dir():
            raise ExecutionError("Test detection workspace must be an existing directory")

    def detect(self) -> list[tuple[str, ...]]:
        commands: list[tuple[str, ...]] = []
        pyproject = self.workspace / "pyproject.toml"
        if pyproject.is_file():
            try:
                config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                config = {}
            if "pytest" in config.get("tool", {}):
                commands.append(("python", "-m", "pytest"))
        if (self.workspace / "tests").is_dir() or (self.workspace / "test").is_dir():
            commands.append(("python", "-m", "pytest"))
        package_json = self.workspace / "package.json"
        if package_json.is_file():
            try:
                package = json.loads(package_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                package = {}
            scripts = package.get("scripts", {})
            if isinstance(scripts, dict):
                for script_name in ("test", "lint", "build"):
                    if isinstance(scripts.get(script_name), str):
                        commands.append(("npm", "run", script_name))
        if (self.workspace / "tsconfig.json").is_file():
            commands.append(("npx", "tsc", "--noEmit"))
        return list(dict.fromkeys(commands))


class DockerCommandRunner:
    def __init__(
        self,
        workspace: Path,
        image: str = "python:3.14-slim",
        timeout_seconds: float = 120.0,
        max_output_chars: int = 50_000,
    ) -> None:
        self.workspace = workspace.expanduser().resolve()
        if not self.workspace.is_dir():
            raise DockerIsolationUnavailable("Execution workspace must be an existing directory")
        if shutil.which("docker") is None:
            raise DockerIsolationUnavailable("Docker is unavailable; refusing host execution fallback")
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars

    def run(self, command: list[str]) -> CommandResult:
        normalized = tuple(command)
        if not normalized or not any(normalized[: len(allowed)] == allowed for allowed in SAFE_COMMANDS):
            raise ExecutionError("Command is not on the approved test command allowlist")
        docker_command = [
            "docker", "run", "--rm", "--pull=never", "--network", "none",
            "--cpus", "2", "--memory", "2g", "--pids-limit", "256",
            "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
            "-v", f"{self.workspace}:/workspace:rw", "-w", "/workspace", self.image,
            *normalized,
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(
                docker_command, capture_output=True, text=True,
                timeout=self.timeout_seconds, check=False, shell=False,
            )
            return CommandResult(
                normalized, completed.returncode,
                completed.stdout[: self.max_output_chars],
                completed.stderr[: self.max_output_chars],
                time.monotonic() - started, isolated=True,
            )
        except subprocess.TimeoutExpired as error:
            return CommandResult(
                normalized, -1, (error.stdout or "")[: self.max_output_chars],
                (error.stderr or "")[: self.max_output_chars],
                time.monotonic() - started, timed_out=True, isolated=True,
            )
        except OSError as error:
            raise DockerIsolationUnavailable(f"Docker command could not start: {error}") from error
