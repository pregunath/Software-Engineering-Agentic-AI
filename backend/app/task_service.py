from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.events import record_event
from app.models import PlanStatus, Task, TaskPlan, TaskStatus
from app.state_machine import InvalidTaskTransition, transition_task


ACTIVE_STATUSES = {
    TaskStatus.QUEUED,
    TaskStatus.PLANNING,
    TaskStatus.AWAITING_APPROVAL,
    TaskStatus.EXECUTING,
    TaskStatus.TESTING,
    TaskStatus.NEEDS_ATTENTION,
}


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


def cancel_task(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    current = TaskStatus(task.status)
    if current == TaskStatus.CANCELLED:
        return task
    if current in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
        raise HTTPException(status_code=409, detail="Terminal tasks cannot be cancelled")
    if current not in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Task cannot be cancelled in its current state")
    result = db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == current.value)
        .values(status=TaskStatus.CANCELLED.value)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Task changed before cancellation completed")
    task.status = TaskStatus.CANCELLED.value
    record_event(db, task_id, "task.cancelled", {"previous_status": current.value})
    record_event(db, task_id, "task.status_changed", {"status": TaskStatus.CANCELLED.value})
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
