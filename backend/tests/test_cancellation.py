from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.agent import AgentOrchestrator, PlanningError
from app.db import SessionLocal, initialize_database
from app.execution import CommandResult, DockerCommandRunner
from app.execution_service import execute_approved_plan
from app.main import app
from app.models import PlanStatus, Task, TaskPlan, TaskStatus
from app.runtime import task_runtime_registry
from app.task_service import cancel_task, update_task_status


def create_task(client: TestClient) -> int:
    response = client.post("/tasks", json={"title": "Cancel me", "description": "Exercise cancellation."})
    return response.json()["id"]


def _advance(client: TestClient, task_id: int, *statuses: str) -> None:
    for status in statuses:
        response = client.patch(f"/tasks/{task_id}/status", json={"status": status})
        assert response.status_code == 200, response.text


def test_queued_cancellation_is_idempotent_and_emits_events() -> None:
    with TestClient(app) as client:
        task_id = create_task(client)
        first = client.post(f"/tasks/{task_id}/cancel")
        second = client.post(f"/tasks/{task_id}/cancel")
        events = client.get(f"/tasks/{task_id}/events").json()

    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    assert second.status_code == 200
    assert second.json()["status"] == "cancelled"
    assert any(event["type"] == "task.cancel_accepted" for event in events)
    assert any(event["type"] == "task.cancelled" for event in events)


def test_awaiting_approval_cancellation() -> None:
    with TestClient(app) as client:
        task_id = create_task(client)
        _advance(client, task_id, "planning", "awaiting_approval")
        response = client.post(f"/tasks/{task_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_planning_cancellation() -> None:
    with TestClient(app) as client:
        task_id = create_task(client)
        _advance(client, task_id, "planning")
        response = client.post(f"/tasks/{task_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_executing_and_testing_cancellation() -> None:
    with TestClient(app) as client:
        task_id = create_task(client)
        _advance(client, task_id, "planning", "awaiting_approval", "executing")
        executing = client.post(f"/tasks/{task_id}/cancel")
        assert executing.status_code == 200

        task_id = create_task(client)
        _advance(client, task_id, "planning", "awaiting_approval", "executing", "testing")
        testing = client.post(f"/tasks/{task_id}/cancel")
        assert testing.status_code == 200
        assert testing.json()["status"] == "cancelled"


def test_completed_failed_and_cancelled_rejection() -> None:
    with TestClient(app) as client:
        completed_id = create_task(client)
        _advance(client, completed_id, "planning", "awaiting_approval", "executing", "testing", "completed")
        assert client.post(f"/tasks/{completed_id}/cancel").status_code == 409

        failed_id = create_task(client)
        _advance(client, failed_id, "planning")
        assert client.patch(f"/tasks/{failed_id}/status", json={"status": "failed"}).status_code == 200
        assert client.post(f"/tasks/{failed_id}/cancel").status_code == 409

        cancelled_id = create_task(client)
        assert client.post(f"/tasks/{cancelled_id}/cancel").status_code == 200
        assert client.post(f"/tasks/{cancelled_id}/cancel").status_code == 200


def test_stale_completion_cannot_overwrite_cancelled_task() -> None:
    with TestClient(app) as client:
        task_id = create_task(client)
        client.post(f"/tasks/{task_id}/cancel")
        stale_completion = client.patch(f"/tasks/{task_id}/status", json={"status": "completed"})

    assert stale_completion.status_code == 409


def test_invalid_lifecycle_transition_rejected() -> None:
    with TestClient(app) as client:
        task_id = create_task(client)
        response = client.patch(f"/tasks/{task_id}/status", json={"status": "completed"})
    assert response.status_code == 409


def test_concurrent_cancel_and_completion_race() -> None:
    initialize_database()
    db = SessionLocal()
    try:
        task = Task(title="Race", description="Concurrent cancel vs complete", status=TaskStatus.TESTING.value)
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
    finally:
        db.close()

    results: dict[str, object] = {}

    def cancel_worker() -> None:
        session = SessionLocal()
        try:
            results["cancel"] = cancel_task(session, task_id).status
        except Exception as error:  # noqa: BLE001 - capture race outcome
            results["cancel_error"] = str(error)
        finally:
            session.close()

    def complete_worker() -> None:
        session = SessionLocal()
        try:
            results["complete"] = update_task_status(session, task_id, TaskStatus.COMPLETED).status
        except Exception as error:  # noqa: BLE001 - expected conflict for loser
            results["complete_error"] = str(error)
        finally:
            session.close()

    first = threading.Thread(target=cancel_worker)
    second = threading.Thread(target=complete_worker)
    first.start()
    second.start()
    first.join()
    second.join()

    final = SessionLocal()
    try:
        status = final.get(Task, task_id).status
    finally:
        final.close()

    assert status in {TaskStatus.CANCELLED.value, TaskStatus.COMPLETED.value}
    if status == TaskStatus.CANCELLED.value:
        assert "complete_error" in results
    else:
        assert "cancel_error" in results


@pytest.mark.asyncio
async def test_delayed_model_response_cannot_restart_cancelled_work() -> None:
    import asyncio

    initialize_database()
    task_runtime_registry.clear()
    db = SessionLocal()

    class SlowProvider:
        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def model_capabilities(self, model: str):
            return type("Caps", (), {"supports_tools": False})()

        async def chat(self, model: str, messages, tools=None):
            self.entered.set()
            await asyncio.wait_for(self.release.wait(), timeout=2)
            return {
                "message": {
                    "role": "assistant",
                    "content": '{"summary":"Late","content":"Should not apply","proposed_diff":""}',
                }
            }

    provider = SlowProvider()
    try:
        task = Task(title="Plan cancel", description="Cancel during LLM", status=TaskStatus.QUEUED.value)
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id

        plan_task = asyncio.create_task(AgentOrchestrator(provider, "test-model", db).generate_plan(task_id))
        await asyncio.wait_for(provider.entered.wait(), timeout=2)

        cancel_db = SessionLocal()
        try:
            cancel_task(cancel_db, task_id)
        finally:
            cancel_db.close()
        provider.release.set()

        with pytest.raises(PlanningError, match="cancelled"):
            await plan_task

        db.refresh(task)
        assert task.status == TaskStatus.CANCELLED.value
        assert db.query(TaskPlan).filter(TaskPlan.task_id == task_id).one_or_none() is None
    finally:
        task_runtime_registry.clear()
        db.close()


def test_late_test_result_cannot_overwrite_cancelled_state(tmp_path: Path, monkeypatch) -> None:
    initialize_database()
    task_runtime_registry.clear()
    (tmp_path / "tests").mkdir()
    target = tmp_path / "main.py"
    target.write_text("return 1\n", encoding="utf-8")
    from difflib import unified_diff

    diff = "".join(unified_diff(["return 1\n"], ["return 2\n"], fromfile="a/main.py", tofile="b/main.py"))

    gate = threading.Event()
    cancelled = threading.Event()

    class BlockingDockerRunner:
        def __init__(self, workspace: Path):
            self.workspace = workspace

        def run(self, command: list[str], should_cancel=None, on_started=None, on_finished=None):
            gate.set()
            assert cancelled.wait(timeout=2)
            # Simulate a late successful test result after cancellation was accepted.
            if should_cancel and should_cancel():
                return CommandResult(tuple(command), -1, "", "cancelled", 0.01, isolated=True, cancelled=True)
            return CommandResult(tuple(command), 0, "passed", "", 0.01, isolated=True)

    monkeypatch.setattr("app.execution_service.DockerCommandRunner", BlockingDockerRunner)
    db = SessionLocal()
    try:
        task = Task(title="Late test", description="Cancel during tests", status=TaskStatus.EXECUTING.value)
        db.add(task)
        db.commit()
        db.refresh(task)
        db.add(
            TaskPlan(
                task_id=task.id,
                summary="Change return",
                content="Apply diff",
                proposed_diff=diff,
                status=PlanStatus.APPROVED.value,
            )
        )
        db.commit()

        errors: list[BaseException] = []

        def run_execution() -> None:
            session = SessionLocal()
            try:
                execute_approved_plan(session, task.id, str(tmp_path))
            except BaseException as error:  # noqa: BLE001
                errors.append(error)
            finally:
                session.close()

        worker = threading.Thread(target=run_execution)
        worker.start()
        assert gate.wait(timeout=2)

        cancel_db = SessionLocal()
        try:
            cancel_task(cancel_db, task.id)
        finally:
            cancel_db.close()
        cancelled.set()
        worker.join(timeout=5)

        db.refresh(task)
        assert task.status == TaskStatus.CANCELLED.value
        events = cancel_db = SessionLocal()
        try:
            from app.events import list_events

            event_types = [event.event_type for event in list_events(events, task.id)]
        finally:
            events.close()
        assert "execution.cancelled" in event_types or "tests.cancelled" in event_types
    finally:
        task_runtime_registry.clear()
        db.close()


def test_cancel_terminates_attached_docker_process(monkeypatch) -> None:
    task_runtime_registry.clear()
    runtime = task_runtime_registry.begin(42, "testing")
    process = MagicMock()
    process.poll.return_value = None
    process.wait.side_effect = [None]
    task_runtime_registry.attach_process(42, process)

    cleanup = task_runtime_registry.request_cancel(42, terminate_timeout_seconds=0.1)

    assert runtime.cancel_event.is_set()
    process.terminate.assert_called_once()
    assert cleanup["process_terminated"] is True
    assert cleanup["cleanup_timed_out"] is False
    task_runtime_registry.end(42)


def test_cancel_timeout_is_reported_when_process_will_not_die() -> None:
    import subprocess

    task_runtime_registry.clear()
    task_runtime_registry.begin(7, "testing")
    process = MagicMock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired(cmd="docker", timeout=0.1)] * 2
    task_runtime_registry.attach_process(7, process)

    cleanup = task_runtime_registry.request_cancel(7, terminate_timeout_seconds=0.05)

    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert cleanup["cleanup_timed_out"] is True
    assert cleanup["process_terminated"] is False
    task_runtime_registry.end(7)


def test_docker_runner_cancel_does_not_touch_foreign_workspace(tmp_path: Path, monkeypatch) -> None:
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    owned = tmp_path / "owned"
    owned.mkdir()
    (foreign / "secret.txt").write_text("keep", encoding="utf-8")

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self._alive = True
            self.returncode = None

        def poll(self):
            return None if self._alive else 0

        def terminate(self):
            self._alive = False
            self.returncode = -15

        def kill(self):
            self._alive = False
            self.returncode = -9

        def communicate(self, timeout=None):
            self._alive = False
            return ("", "terminated")

        def wait(self, timeout=None):
            self._alive = False
            return self.returncode

    monkeypatch.setattr("app.execution.shutil.which", lambda _: "docker")
    monkeypatch.setattr("app.execution.subprocess.Popen", FakePopen)

    cancelled = {"value": False}

    def should_cancel() -> bool:
        if not cancelled["value"]:
            cancelled["value"] = True
            return False
        return True

    result = DockerCommandRunner(owned, terminate_timeout_seconds=0.1).run(
        ["python", "-m", "pytest"],
        should_cancel=should_cancel,
    )
    assert result.cancelled is True
    assert (foreign / "secret.txt").read_text(encoding="utf-8") == "keep"


def test_cancellation_cleanup_runs_even_when_event_recording_raises(monkeypatch) -> None:
    initialize_database()
    task_runtime_registry.clear()
    db = SessionLocal()
    task_id: int | None = None
    try:
        task = Task(title="Cleanup", description="Force cleanup", status=TaskStatus.EXECUTING.value)
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
        runtime = task_runtime_registry.begin(task.id, "executing")
        process = MagicMock()
        process.poll.return_value = None
        process.wait.return_value = 0
        task_runtime_registry.attach_process(task.id, process)

        original_record = __import__("app.events", fromlist=["record_event"]).record_event

        def flaky_record(session, event_task_id, event_type, payload):
            if event_type == "task.cancelled":
                raise RuntimeError("event bus unavailable")
            return original_record(session, event_task_id, event_type, payload)

        monkeypatch.setattr("app.task_service.record_event", flaky_record)
        with pytest.raises(RuntimeError, match="event bus unavailable"):
            cancel_task(db, task.id)

        assert runtime.cancel_event.is_set()
        process.terminate.assert_called()
    finally:
        if task_id is not None:
            task_runtime_registry.end(task_id)
        task_runtime_registry.clear()
        db.close()
