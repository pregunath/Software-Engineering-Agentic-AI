from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.events import format_sse, list_events, record_event
from app.models import Task, TaskStatus
from app.schemas import TaskCreate, TaskRead, TaskStatusUpdate
from app.task_service import cancel_task, retry_needs_attention_task, update_task_status

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(task_input: TaskCreate, db: Session = Depends(get_db)) -> Task:
    task = Task(
        title=task_input.title,
        description=task_input.description,
        status=TaskStatus.QUEUED.value,
        workspace_id=task_input.workspace_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    record_event(db, task.id, "task.created", {"status": task.status, "title": task.title})
    db.commit()
    return task


@router.get("", response_model=list[TaskRead])
def list_tasks(db: Session = Depends(get_db)) -> list[Task]:
    return list(db.scalars(select(Task).order_by(Task.created_at.desc())).all())


@router.patch("/{task_id}/status", response_model=TaskRead)
def change_task_status(
    task_id: int, status_input: TaskStatusUpdate, db: Session = Depends(get_db)
) -> Task:
    return update_task_status(db, task_id, status_input.status)


@router.post("/{task_id}/cancel", response_model=TaskRead)
def cancel_task_endpoint(task_id: int, db: Session = Depends(get_db)) -> Task:
    return cancel_task(db, task_id)


@router.post("/{task_id}/retry", response_model=TaskRead)
def retry_task_endpoint(task_id: int, db: Session = Depends(get_db)) -> Task:
    return retry_needs_attention_task(db, task_id)


@router.get("/{task_id}/events")
def task_events(task_id: int, db: Session = Depends(get_db)) -> list[dict[str, object]]:
    if db.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return [
        {"id": event.id, "type": event.event_type, "payload": event.payload}
        for event in list_events(db, task_id)
    ]


@router.get("/{task_id}/events/stream")
def task_event_stream(task_id: int, db: Session = Depends(get_db)) -> StreamingResponse:
    if db.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return StreamingResponse(
        iter([format_sse(list_events(db, task_id))]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
