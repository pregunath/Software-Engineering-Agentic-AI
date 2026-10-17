from __future__ import annotations

import json
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TaskEvent


def record_event(db: Session, task_id: int, event_type: str, payload: dict[str, object]) -> TaskEvent:
    event = TaskEvent(task_id=task_id, event_type=event_type, payload=json.dumps(payload, sort_keys=True))
    db.add(event)
    db.flush()
    return event


def list_events(db: Session, task_id: int) -> list[TaskEvent]:
    return list(db.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id)).all())


def format_sse(events: Iterable[TaskEvent]) -> str:
    chunks: list[str] = []
    for event in events:
        chunks.append(
            f"id: {event.id}\nevent: {event.event_type}\ndata: {event.payload}\n\n"
        )
    return "".join(chunks)
