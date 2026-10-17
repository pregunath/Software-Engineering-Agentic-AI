from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.events import record_event
from app.execution import DockerCommandRunner, ProjectTestCommandDetector
from app.models import PlanStatus, Task, TaskPlan, TaskStatus
from app.patching import PatchError, WorkspaceEditor
from app.runtime import DuplicateWorkerError, task_runtime_registry
from app.task_service import TaskCancelled, ensure_task_continuable, update_task_status


def _is_cancelled(task_id: int) -> bool:
    if task_runtime_registry.is_cancel_requested(task_id):
        return True
    probe = SessionLocal()
    try:
        current = probe.get(Task, task_id)
        return current is None or current.status == TaskStatus.CANCELLED.value
    finally:
        probe.close()


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
        runtime = task_runtime_registry.begin(task_id, "executing")
    except DuplicateWorkerError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    workspace = Path(workspace_path)
    try:
        ensure_task_continuable(db, task_id, {TaskStatus.EXECUTING})
        if not plan.proposed_diff.strip():
            raise PatchError("Approved plan contains no proposed diff")

        editor = WorkspaceEditor(workspace)
        checkpoint = editor.apply_unified_diff(plan.proposed_diff)
        record_event(db, task_id, "patch.applied", {"checkpoint": checkpoint.id})
        db.commit()

        ensure_task_continuable(db, task_id, {TaskStatus.EXECUTING})
        update_task_status(db, task_id, TaskStatus.TESTING)

        commands = ProjectTestCommandDetector(workspace).detect()
        if not commands:
            raise PatchError("No approved test command was detected")

        runtime.phase = "testing"
        runner = DockerCommandRunner(workspace)
        results: list[dict[str, object]] = []
        for command in commands:
            ensure_task_continuable(db, task_id, {TaskStatus.TESTING})
            result = runner.run(
                list(command),
                should_cancel=lambda: _is_cancelled(task_id),
                on_started=lambda process: task_runtime_registry.attach_process(task_id, process),
                on_finished=lambda: task_runtime_registry.clear_process(task_id),
            )
            if result.cancelled or _is_cancelled(task_id):
                record_event(
                    db,
                    task_id,
                    "tests.cancelled",
                    {
                        "command": list(command),
                        "cancel_timed_out": result.cancel_timed_out,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    },
                )
                db.commit()
                if result.cancel_timed_out:
                    record_event(
                        db,
                        task_id,
                        "task.cancel_cleanup_failed",
                        {"detail": "Docker termination timed out during test cancellation"},
                    )
                    db.commit()
                raise TaskCancelled(f"Task {task_id} was cancelled during test execution")
            results.append(
                {
                    "command": list(command),
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )

        # Late test results must not overwrite a cancelled task.
        ensure_task_continuable(db, task_id, {TaskStatus.TESTING})
        all_passed = all(item["exit_code"] == 0 and not item["timed_out"] for item in results)
        record_event(db, task_id, "tests.completed", {"passed": all_passed, "results": results})
        db.commit()
        update_task_status(
            db,
            task_id,
            TaskStatus.COMPLETED if all_passed else TaskStatus.NEEDS_ATTENTION,
        )
        return db.get(Task, task_id)
    except TaskCancelled as error:
        record_event(db, task_id, "execution.cancelled", {"detail": str(error)})
        db.commit()
        cancelled = db.get(Task, task_id)
        if cancelled is None:
            raise HTTPException(status_code=404, detail="Task not found") from error
        return cancelled
    except (PatchError, OSError, ValueError, HTTPException) as error:
        detail = error.detail if isinstance(error, HTTPException) else str(error)
        current = db.get(Task, task_id)
        if current is not None and current.status == TaskStatus.CANCELLED.value:
            record_event(db, task_id, "execution.cancelled", {"detail": detail})
            db.commit()
            return current
        if isinstance(error, HTTPException) and error.status_code == 409 and "cancelled" in detail.lower():
            raise
        record_event(db, task_id, "execution.failed", {"detail": detail})
        db.commit()
        current = db.get(Task, task_id)
        if current is not None and current.status in {
            TaskStatus.EXECUTING.value,
            TaskStatus.TESTING.value,
        }:
            try:
                update_task_status(db, task_id, TaskStatus.NEEDS_ATTENTION)
            except HTTPException:
                # Task may have been cancelled concurrently; leave authoritative state alone.
                pass
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(status_code=409, detail=detail) from error
    finally:
        task_runtime_registry.end(task_id)
