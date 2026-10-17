from fastapi.testclient import TestClient

from app.main import app


def test_create_and_list_task() -> None:
    with TestClient(app) as client:
        create_response = client.post(
            "/tasks",
            json={"title": "Fix parser", "description": "Investigate the parser failure."},
        )
        list_response = client.get("/tasks")

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["title"] == "Fix parser"
    assert created["status"] == "queued"
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == created["id"]


def test_task_input_is_validated() -> None:
    with TestClient(app) as client:
        response = client.post("/tasks", json={"title": "", "description": ""})

    assert response.status_code == 422
