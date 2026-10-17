from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.events import record_event
from app.models import PlanStatus, Task, TaskPlan, TaskStatus
from app.runtime import task_runtime_registry
from app.state_machine import InvalidTaskTransition, transition_task


ACTIVE_STATUSES = {
    TaskStatus.QUEUED,
    TaskStatus.PLANNING,
    TaskStatus.AWAITING_APPROVAL,
    TaskStatus.EXECUTING,
    TaskStatus.TESTING,
    TaskStatus.NEEDS_ATTENTION,
}

TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


class TaskCancelled(RuntimeError):
    """Raised when a worker observes that its task was cancelled."""


def update_task_status(db: Session, task_id: int, target: TaskStatus) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    current = TaskStatus(task.status)
    try:
        transition_task(current, target)
    except (InvalidTaskTransition, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    result = db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == current.value)
        .values(status=target.value)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Task changed before this transition completed")
    task.status = target.value
    record_event(db, task.id, "task.status_changed", {"status": task.status})
    db.commit()
    db.refresh(task)
    return task


def ensure_task_continuable(db: Session, task_id: int, allowed: set[TaskStatus]) -> Task:
    """Revalidate worker authority before consequential work or final state writes.

    Uses the in-process cancel signal and a fresh DB read so long-lived worker sessions
    cannot miss a concurrent cancellation commit.
    """
    if task_runtime_registry.is_cancel_requested(task_id):
        raise TaskCancelled(f"Task {task_id} was cancelled")
    probe = SessionLocal()
    try:
        snapshot = probe.get(Task, task_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Task not found")
        current = TaskStatus(snapshot.status)
    finally:
        probe.close()
    if current == TaskStatus.CANCELLED:
        raise TaskCancelled(f"Task {task_id} was cancelled")
    if current not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Task is not in an allowed state for this operation (current={current.value})",
        )
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    db.refresh(task)
    return task


def cancel_task(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    current = TaskStatus(task.status)
    if current == TaskStatus.CANCELLED:
        return task
    if current in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Terminal tasks cannot be cancelled")
    if current not in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Task cannot be cancelled in its current state")

    # Persist cancelled state first so workers revalidating from the DB cannot
    # observe a cancel signal while the authoritative row is still active.
    record_event(db, task_id, "task.cancel_accepted", {"previous_status": current.value})
    result = db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == current.value)
        .values(status=TaskStatus.CANCELLED.value)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Task changed before cancellation completed")
    task.status = TaskStatus.CANCELLED.value
    record_event(db, task_id, "task.status_changed", {"status": TaskStatus.CANCELLED.value})
    db.commit()
    db.refresh(task)

    cleanup = task_runtime_registry.request_cancel(task_id)
    record_event(
        db,
        task_id,
        "task.cancelled",
        {
            "previous_status": current.value,
            "worker_active": cleanup["worker_active"],
            "process_terminated": cleanup["process_terminated"],
            "cleanup_timed_out": cleanup["cleanup_timed_out"],
        },
    )
    if cleanup["cleanup_timed_out"] and cleanup["process_terminated"] is False:
        record_event(
            db,
            task_id,
            "task.cancel_cleanup_failed",
            {"detail": "Owned Docker/process termination timed out"},
        )
    db.commit()
    db.refresh(task)
    return task


def approve_plan(db: Session, task_id: int) -> TaskPlan:
    plan = db.query(TaskPlan).filter(TaskPlan.task_id == task_id).one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan.status != PlanStatus.AWAITING_APPROVAL.value:
        raise HTTPException(status_code=409, detail="Plan is no longer awaiting approval")
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    current = TaskStatus(task.status)
    if current == TaskStatus.CANCELLED or task_runtime_registry.is_cancel_requested(task_id):
        raise HTTPException(status_code=409, detail="Cancelled tasks cannot be approved")
    try:
        transition_task(current, TaskStatus.EXECUTING)
    except (InvalidTaskTransition, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    result = db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == current.value)
        .values(status=TaskStatus.EXECUTING.value)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Task changed before approval completed")
    task.status = TaskStatus.EXECUTING.value
    plan.status = PlanStatus.APPROVED.value
    plan.approved_at = datetime.utcnow()
    record_event(db, task.id, "plan.approved", {"plan_id": plan.id})
    record_event(db, task.id, "task.status_changed", {"status": task.status})
    db.commit()
    db.refresh(plan)
    return plan


def retry_needs_attention_task(db: Session, task_id: int) -> Task:
    """Conservative user-directed recovery for interrupted tasks with no uncertain patch."""
    from app.events import list_events

    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if TaskStatus(task.status) != TaskStatus.NEEDS_ATTENTION:
        raise HTTPException(status_code=409, detail="Only needs_attention tasks can be retried")

    events = list_events(db, task_id)
    patch_applied = any(event.event_type == "patch.applied" for event in events)
    plan = db.query(TaskPlan).filter(TaskPlan.task_id == task_id).one_or_none()

    if patch_applied:
        raise HTTPException(
            status_code=409,
            detail="Partial execution already applied changes; inspect the disposable workspace before retrying",
        )

    if plan is None:
        target = TaskStatus.QUEUED
        decision = "resume_planning"
    elif plan.status == PlanStatus.APPROVED.value:
        target = TaskStatus.EXECUTING
        decision = "resume_execution"
    elif plan.status == PlanStatus.AWAITING_APPROVAL.value:
        target = TaskStatus.AWAITING_APPROVAL
        decision = "resume_approval"
    else:
        raise HTTPException(status_code=409, detail="Plan state does not support safe retry")

    updated = update_task_status(db, task_id, target)
    record_event(db, task_id, "task.retry_accepted", {"decision": decision, "status": target.value})
    db.commit()
    db.refresh(updated)
    return updated
