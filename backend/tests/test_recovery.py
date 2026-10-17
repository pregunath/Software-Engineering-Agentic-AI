from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.db import SessionLocal, initialize_database
from app.events import list_events, record_event
from app.main import app
from app.models import PlanStatus, Task, TaskPlan, TaskStatus
from app.recovery import recover_interrupted_tasks
from app.runtime import task_runtime_registry
from app.task_service import retry_needs_attention_task


def test_recovery_marks_interrupted_tasks_needs_attention_and_records_event() -> None:
    initialize_database()
    task_runtime_registry.clear()
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
        events = list_events(db, task.id)
        recovered_events = [event for event in events if event.event_type == "task.recovered"]
        assert recovered_events
        assert "previous_status" in recovered_events[0].payload
    finally:
        db.close()


def test_recovery_leaves_completed_and_failed_unchanged() -> None:
    initialize_database()
    db = SessionLocal()
    try:
        completed = Task(title="Done", description="Keep me", status=TaskStatus.COMPLETED.value)
        failed = Task(title="Broken", description="Keep me too", status=TaskStatus.FAILED.value)
        queued = Task(title="Queued", description="Idle is fine", status=TaskStatus.QUEUED.value)
        awaiting = Task(
            title="Awaiting",
            description="Safe idle approval state",
            status=TaskStatus.AWAITING_APPROVAL.value,
        )
        db.add_all([completed, failed, queued, awaiting])
        db.commit()
        for task in (completed, failed, queued, awaiting):
            db.refresh(task)
        recover_interrupted_tasks()
        db.refresh(completed)
        db.refresh(failed)
        db.refresh(queued)
        db.refresh(awaiting)
        assert completed.status == TaskStatus.COMPLETED.value
        assert failed.status == TaskStatus.FAILED.value
        assert queued.status == TaskStatus.QUEUED.value
        assert awaiting.status == TaskStatus.AWAITING_APPROVAL.value
    finally:
        db.close()


def test_recovery_does_not_create_duplicate_workers() -> None:
    initialize_database()
    task_runtime_registry.begin(99, "testing")
    recover_interrupted_tasks()
    assert task_runtime_registry.get(99) is None


def test_uncertain_partial_execution_is_not_blindly_retried() -> None:
    initialize_database()
    db = SessionLocal()
    try:
        task = Task(title="Partial", description="Patch already applied", status=TaskStatus.EXECUTING.value)
        db.add(task)
        db.commit()
        db.refresh(task)
        db.add(
            TaskPlan(
                task_id=task.id,
                summary="Partial",
                content="Already patched",
                proposed_diff="diff",
                status=PlanStatus.APPROVED.value,
            )
        )
        record_event(db, task.id, "patch.applied", {"checkpoint": "abc"})
        db.commit()
        recover_interrupted_tasks()
        db.refresh(task)
        assert task.status == TaskStatus.NEEDS_ATTENTION.value
        with pytest.raises(HTTPException) as error:
            retry_needs_attention_task(db, task.id)
        assert error.value.status_code == 409
        db.refresh(task)
        assert task.status == TaskStatus.NEEDS_ATTENTION.value
        events = list_events(db, task.id)
        payload = next(event.payload for event in events if event.event_type == "task.recovered")
        assert "partial" in payload.lower() or "inspect" in payload.lower()
    finally:
        db.close()


def test_safe_retry_path_for_interrupted_execution_without_patch() -> None:
    initialize_database()
    db = SessionLocal()
    try:
        task = Task(title="Retryable", description="No patch yet", status=TaskStatus.EXECUTING.value)
        db.add(task)
        db.commit()
        db.refresh(task)
        db.add(
            TaskPlan(
                task_id=task.id,
                summary="Ready",
                content="Approved plan",
                proposed_diff="diff",
                status=PlanStatus.APPROVED.value,
            )
        )
        db.commit()
        recover_interrupted_tasks()
        db.refresh(task)
        assert task.status == TaskStatus.NEEDS_ATTENTION.value
        retried = retry_needs_attention_task(db, task.id)
        assert retried.status == TaskStatus.EXECUTING.value
    finally:
        db.close()


def test_retry_endpoint_and_recovery_events_visible_via_api() -> None:
    initialize_database()
    with TestClient(app) as client:
        created = client.post("/tasks", json={"title": "API recover", "description": "via http"})
        task_id = created.json()["id"]
        db = SessionLocal()
        try:
            task = db.get(Task, task_id)
            task.status = TaskStatus.PLANNING.value
            db.commit()
        finally:
            db.close()
        recover_interrupted_tasks()
        events = client.get(f"/tasks/{task_id}/events").json()
        assert any(event["type"] == "task.recovered" for event in events)
        retry = client.post(f"/tasks/{task_id}/retry")
        assert retry.status_code == 200
        assert retry.json()["status"] == "queued"
