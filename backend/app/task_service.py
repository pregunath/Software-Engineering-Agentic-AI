from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.events import record_event
from app.models import PlanStatus, Task, TaskPlan, TaskStatus
from app.state_machine import InvalidTaskTransition, transition_task


def update_task_status(db: Session, task_id: int, target: TaskStatus) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        task.status = transition_task(TaskStatus(task.status), target).value
    except (InvalidTaskTransition, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    record_event(db, task.id, "task.status_changed", {"status": task.status})
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
    try:
        transition_task(TaskStatus(task.status), TaskStatus.EXECUTING)
    except (InvalidTaskTransition, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    task.status = TaskStatus.EXECUTING.value
    plan.status = PlanStatus.APPROVED.value
    plan.approved_at = datetime.utcnow()
    record_event(db, task.id, "plan.approved", {"plan_id": plan.id})
    record_event(db, task.id, "task.status_changed", {"status": task.status})
    db.commit()
    db.refresh(plan)
    return plan
