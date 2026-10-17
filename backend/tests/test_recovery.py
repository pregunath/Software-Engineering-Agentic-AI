from app.db import SessionLocal, initialize_database
from app.models import Task, TaskStatus
from app.recovery import recover_interrupted_tasks


def test_recovery_marks_interrupted_tasks_needs_attention_and_records_event() -> None:
    initialize_database()
    db = SessionLocal()
    try:
        task = Task(title="Interrupted", description="Recover me", status=TaskStatus.TESTING.value)
        db.add(task)
        db.commit()
        db.refresh(task)
        recovered = recover_interrupted_tasks()
        db.refresh(task)
        assert recovered >= 1
        assert task.status == TaskStatus.NEEDS_ATTENTION.value
    finally:
        db.close()
