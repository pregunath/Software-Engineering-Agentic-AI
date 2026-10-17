from fastapi.testclient import TestClient

from app.main import app


def test_task_events_are_persisted_and_replayed_as_sse() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/tasks", json={"title": "Event task", "description": "Track progress."}
        ).json()
        client.patch(f"/tasks/{created['id']}/status", json={"status": "planning"})
        history = client.get(f"/tasks/{created['id']}/events")
        stream = client.get(f"/tasks/{created['id']}/events/stream")

    assert history.status_code == 200
    events = history.json()
    assert [event["type"] for event in events] == [
        "task.created",
        "task.status_changed",
    ]
    assert events[0]["id"] < events[1]["id"]
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: task.created" in stream.text
    assert "event: task.status_changed" in stream.text


def test_missing_task_event_stream_returns_not_found() -> None:
    with TestClient(app) as client:
        response = client.get("/tasks/999999/events/stream")

    assert response.status_code == 404
