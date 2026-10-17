from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.events import record_event
from app.execution import DockerCommandRunner, ProjectTestCommandDetector
from app.models import PlanStatus, Task, TaskPlan, TaskStatus
from app.patching import PatchError, WorkspaceEditor
from app.task_service import update_task_status


def execute_approved_plan(db: Session, task_id: int, workspace_path: str) -> Task:
    task = db.get(Task, task_id)
    plan = db.query(TaskPlan).filter(TaskPlan.task_id == task_id).one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if plan is None or plan.status != PlanStatus.APPROVED.value:
        raise HTTPException(status_code=409, detail="An approved plan is required")
    if task.status != TaskStatus.EXECUTING.value:
        raise HTTPException(status_code=409, detail="Task is not ready for execution")
    try:
        editor = WorkspaceEditor(Path(workspace_path))
        if not plan.proposed_diff.strip():
            raise PatchError("Approved plan contains no proposed diff")
        checkpoint = editor.apply_unified_diff(plan.proposed_diff)
        record_event(db, task_id, "patch.applied", {"checkpoint": checkpoint.id})
        update_task_status(db, task_id, TaskStatus.TESTING)
        commands = ProjectTestCommandDetector(Path(workspace_path)).detect()
        if not commands:
            raise PatchError("No approved test command was detected")
        runner = DockerCommandRunner(Path(workspace_path))
        results = []
        for command in commands:
            result = runner.run(list(command))
            results.append({"command": list(command), "exit_code": result.exit_code, "timed_out": result.timed_out, "stdout": result.stdout, "stderr": result.stderr})
        all_passed = all(result["exit_code"] == 0 and not result["timed_out"] for result in results)
        record_event(db, task_id, "tests.completed", {"passed": all_passed, "results": results})
        update_task_status(db, task_id, TaskStatus.COMPLETED if all_passed else TaskStatus.NEEDS_ATTENTION)
        return db.get(Task, task_id)
    except (PatchError, OSError, ValueError) as error:
        record_event(db, task_id, "execution.failed", {"detail": str(error)})
        db.commit()
        if task.status in {TaskStatus.EXECUTING.value, TaskStatus.TESTING.value}:
            update_task_status(db, task_id, TaskStatus.NEEDS_ATTENTION)
        raise HTTPException(status_code=409, detail=str(error)) from error
