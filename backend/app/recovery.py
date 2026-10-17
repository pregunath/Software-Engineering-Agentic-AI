from sqlalchemy import select, update

from app.db import SessionLocal
from app.events import record_event
from app.models import Task, TaskStatus


INTERRUPTED_STATUSES = {
    TaskStatus.PLANNING.value,
    TaskStatus.EXECUTING.value,
    TaskStatus.TESTING.value,
}


def recover_interrupted_tasks() -> int:
    db = SessionLocal()
    recovered = 0
    try:
        tasks = list(db.scalars(select(Task).where(Task.status.in_(INTERRUPTED_STATUSES))).all())
        for task in tasks:
            result = db.execute(
                update(Task)
                .where(Task.id == task.id, Task.status == task.status)
                .values(status=TaskStatus.NEEDS_ATTENTION.value)
            )
            if result.rowcount == 1:
                record_event(
                    db,
                    task.id,
                    "task.recovered",
                    {"previous_status": task.status, "decision": "needs_attention"},
                )
                recovered += 1
        db.commit()
        return recovered
    finally:
        db.close()
