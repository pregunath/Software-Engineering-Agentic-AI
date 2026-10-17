from difflib import unified_diff
from pathlib import Path

from app.db import SessionLocal, initialize_database
from app.execution import CommandResult
from app.execution_service import execute_approved_plan
from app.models import PlanStatus, Task, TaskPlan, TaskStatus


def test_approved_diff_and_detected_test_complete_task(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "tests").mkdir()
    target = tmp_path / "main.py"
    target.write_text("return 1\n", encoding="utf-8")
    diff = "".join(unified_diff(["return 1\n"], ["return 2\n"], fromfile="a/main.py", tofile="b/main.py"))

    class FakeDockerRunner:
        def __init__(self, workspace: Path):
            self.workspace = workspace

        def run(self, command: list[str]) -> CommandResult:
            return CommandResult(tuple(command), 0, "passed", "", 0.01, isolated=True)

    monkeypatch.setattr("app.execution_service.DockerCommandRunner", FakeDockerRunner)
    initialize_database()
    db = SessionLocal()
    try:
        task = Task(title="Execute task", description="Apply approved change.", status=TaskStatus.EXECUTING.value)
        db.add(task)
        db.commit()
        db.refresh(task)
        db.add(TaskPlan(task_id=task.id, summary="Change return", content="Apply diff", proposed_diff=diff, status=PlanStatus.APPROVED.value))
        db.commit()
        result = execute_approved_plan(db, task.id, str(tmp_path))
        assert result.status == TaskStatus.COMPLETED.value
        assert target.read_text(encoding="utf-8") == "return 2\n"
    finally:
        db.close()
