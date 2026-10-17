from __future__ import annotations

import json
import shutil
import subprocess
import time
import tomllib
from collections.abc import Callable
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
    cancelled: bool = False
    cancel_timed_out: bool = False


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
                list(normalized),
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
            return CommandResult(
                normalized,
                completed.returncode,
                completed.stdout[: self.max_output_chars],
                completed.stderr[: self.max_output_chars],
                time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as error:
            stdout = (error.stdout or "")[: self.max_output_chars]
            stderr = (error.stderr or "")[: self.max_output_chars]
            return CommandResult(
                normalized,
                -1,
                stdout,
                stderr,
                time.monotonic() - started,
                timed_out=True,
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
        terminate_timeout_seconds: float = 5.0,
    ) -> None:
        self.workspace = workspace.expanduser().resolve()
        if not self.workspace.is_dir():
            raise DockerIsolationUnavailable("Execution workspace must be an existing directory")
        if shutil.which("docker") is None:
            raise DockerIsolationUnavailable("Docker is unavailable; refusing host execution fallback")
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars
        self.terminate_timeout_seconds = terminate_timeout_seconds

    def _stop_process(self, process: subprocess.Popen[str]) -> tuple[str, str, bool]:
        process.terminate()
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=self.terminate_timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            try:
                stdout, stderr = process.communicate(timeout=self.terminate_timeout_seconds)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
                timed_out = True
        return stdout or "", stderr or "", timed_out

    def run(
        self,
        command: list[str],
        should_cancel: Callable[[], bool] | None = None,
        on_started: Callable[[subprocess.Popen[str]], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> CommandResult:
        normalized = tuple(command)
        if not normalized or not any(normalized[: len(allowed)] == allowed for allowed in SAFE_COMMANDS):
            raise ExecutionError("Command is not on the approved test command allowlist")
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network",
            "none",
            "--cpus",
            "2",
            "--memory",
            "2g",
            "--pids-limit",
            "256",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",
            "-v",
            f"{self.workspace}:/workspace:rw",
            "-w",
            "/workspace",
            self.image,
            *normalized,
        ]
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                docker_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
            )
            if on_started is not None:
                on_started(process)
            try:
                while process.poll() is None:
                    if should_cancel and should_cancel():
                        stdout, stderr, cancel_timed_out = self._stop_process(process)
                        return CommandResult(
                            normalized,
                            -1,
                            stdout[: self.max_output_chars],
                            stderr[: self.max_output_chars],
                            time.monotonic() - started,
                            isolated=True,
                            cancelled=True,
                            cancel_timed_out=cancel_timed_out,
                        )
                    if time.monotonic() - started >= self.timeout_seconds:
                        stdout, stderr, _ = self._stop_process(process)
                        return CommandResult(
                            normalized,
                            -1,
                            stdout[: self.max_output_chars],
                            stderr[: self.max_output_chars],
                            time.monotonic() - started,
                            timed_out=True,
                            isolated=True,
                        )
                    time.sleep(0.05)
                stdout, stderr = process.communicate()
                return CommandResult(
                    normalized,
                    process.returncode if process.returncode is not None else -1,
                    stdout[: self.max_output_chars],
                    stderr[: self.max_output_chars],
                    time.monotonic() - started,
                    isolated=True,
                )
            finally:
                if on_finished is not None:
                    on_finished()
        except OSError as error:
            raise DockerIsolationUnavailable(f"Docker command could not start: {error}") from error
