from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_local_ollama_configuration() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["environment"] == "development"
    assert payload["ollama"]["base_url"] == "http://localhost:11434"
    assert payload["ollama"]["model"] == "gemma4:e2b"


def test_database_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health/database")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
