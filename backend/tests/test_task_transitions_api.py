from fastapi.testclient import TestClient

from app.main import app


def create_task(client: TestClient) -> int:
    response = client.post(
        "/tasks", json={"title": "Transition me", "description": "Test state changes."}
    )
    return response.json()["id"]


def test_status_endpoint_enforces_transition_order() -> None:
    with TestClient(app) as client:
        task_id = create_task(client)
        invalid = client.patch(f"/tasks/{task_id}/status", json={"status": "executing"})
        planning = client.patch(f"/tasks/{task_id}/status", json={"status": "planning"})
        approval = client.patch(
            f"/tasks/{task_id}/status", json={"status": "awaiting_approval"}
        )

    assert invalid.status_code == 409
    assert planning.status_code == 200
    assert approval.json()["status"] == "awaiting_approval"
