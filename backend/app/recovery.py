from __future__ import annotations

from sqlalchemy import select, update

from app.db import SessionLocal
from app.events import list_events, record_event
from app.models import Task, TaskPlan, TaskStatus
from app.runtime import task_runtime_registry


# Only statuses that imply an in-flight worker may have been interrupted mid-operation.
INTERRUPTED_STATUSES = {
    TaskStatus.PLANNING.value,
    TaskStatus.EXECUTING.value,
    TaskStatus.TESTING.value,
}


def _recovery_decision(db, task: Task) -> dict[str, object]:
    """Decide recovery action without blindly repeating uncertain work."""
    events = list_events(db, task.id)
    event_types = {event.event_type for event in events}
    plan = db.query(TaskPlan).filter(TaskPlan.task_id == task.id).one_or_none()
    patch_applied = "patch.applied" in event_types
    tests_started = "tests.completed" in event_types or "tests.cancelled" in event_types

    if task.status == TaskStatus.PLANNING.value:
        return {
            "decision": "needs_attention",
            "safe_to_auto_resume": False,
            "suggested_retry": "planning" if plan is None else None,
            "reason": "Planning was interrupted; regenerate the plan after review",
            "partial_patch": False,
        }

    if patch_applied or tests_started:
        return {
            "decision": "needs_attention",
            "safe_to_auto_resume": False,
            "suggested_retry": None,
            "reason": "Execution may have partially completed; inspect the disposable workspace before retrying",
            "partial_patch": patch_applied,
        }

    if plan is not None and task.status in {TaskStatus.EXECUTING.value, TaskStatus.TESTING.value}:
        return {
            "decision": "needs_attention",
            "safe_to_auto_resume": False,
            "suggested_retry": "execution",
            "reason": "Execution was interrupted before a patch was applied; user-directed retry is available",
            "partial_patch": False,
        }

    return {
        "decision": "needs_attention",
        "safe_to_auto_resume": False,
        "suggested_retry": None,
        "reason": "Active work was interrupted by process restart",
        "partial_patch": False,
    }


def recover_interrupted_tasks() -> int:
    """Conservative startup recovery: detect interrupted work, never spawn duplicate workers."""
    task_runtime_registry.clear()
    db = SessionLocal()
    recovered = 0
    try:
        tasks = list(db.scalars(select(Task).where(Task.status.in_(INTERRUPTED_STATUSES))).all())
        for task in tasks:
            decision = _recovery_decision(db, task)
            result = db.execute(
                update(Task)
                .where(Task.id == task.id, Task.status == task.status)
                .values(status=TaskStatus.NEEDS_ATTENTION.value)
            )
            if result.rowcount != 1:
                continue
            record_event(
                db,
                task.id,
                "task.recovered",
                {
                    "previous_status": task.status,
                    **decision,
                },
            )
            record_event(
                db,
                task.id,
                "task.status_changed",
                {"status": TaskStatus.NEEDS_ATTENTION.value},
            )
            recovered += 1
        db.commit()
        return recovered
    finally:
        db.close()
