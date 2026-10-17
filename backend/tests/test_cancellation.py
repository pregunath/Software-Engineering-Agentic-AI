from fastapi.testclient import TestClient

from app.main import app


def create_task(client: TestClient) -> int:
    response = client.post("/tasks", json={"title": "Cancel me", "description": "Exercise cancellation."})
    return response.json()["id"]


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
    assert any(event["type"] == "task.cancelled" for event in events)


def test_completed_task_cannot_be_cancelled() -> None:
    with TestClient(app) as client:
        task_id = create_task(client)
        client.patch(f"/tasks/{task_id}/status", json={"status": "planning"})
        client.patch(f"/tasks/{task_id}/status", json={"status": "awaiting_approval"})
        client.patch(f"/tasks/{task_id}/status", json={"status": "executing"})
        client.patch(f"/tasks/{task_id}/status", json={"status": "testing"})
        client.patch(f"/tasks/{task_id}/status", json={"status": "completed"})
        response = client.post(f"/tasks/{task_id}/cancel")

    assert response.status_code == 409


def test_stale_completion_cannot_overwrite_cancelled_task() -> None:
    with TestClient(app) as client:
        task_id = create_task(client)
        client.post(f"/tasks/{task_id}/cancel")
        stale_completion = client.patch(f"/tasks/{task_id}/status", json={"status": "completed"})

    assert stale_completion.status_code == 409
