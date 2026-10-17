import os
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@contextmanager
def configured_app(**env: str) -> Iterator:
    previous = {key: os.environ.get(key) for key in env}
    get_settings.cache_clear()
    try:
        for key, value in env.items():
            os.environ[key] = value
        yield create_app()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


def test_protected_routes_open_without_api_key_in_development() -> None:
    with configured_app(AGENT_ENVIRONMENT="development", AGENT_API_KEY="") as app:
        with TestClient(app) as client:
            response = client.get("/tasks")
    assert response.status_code == 200


def test_api_key_required_when_configured() -> None:
    with configured_app(AGENT_ENVIRONMENT="development", AGENT_API_KEY="secret-key") as app:
        with TestClient(app) as client:
            denied = client.get("/tasks")
            allowed = client.get("/tasks", headers={"Authorization": "Bearer secret-key"})
            health = client.get("/health")
    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert health.status_code == 200


def test_production_without_api_key_rejects_protected_routes() -> None:
    with configured_app(AGENT_ENVIRONMENT="production", AGENT_API_KEY="") as app:
        with TestClient(app) as client:
            response = client.get("/tasks")
            health = client.get("/health")
    assert response.status_code == 503
    assert health.status_code == 200


def test_cors_origins_from_settings() -> None:
    with configured_app(
        AGENT_ENVIRONMENT="development",
        AGENT_API_KEY="",
        AGENT_CORS_ORIGINS="https://forge.example.com,http://localhost:3000",
    ) as app:
        with TestClient(app) as client:
            response = client.options(
                "/tasks",
                headers={
                    "Origin": "https://forge.example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://forge.example.com"
