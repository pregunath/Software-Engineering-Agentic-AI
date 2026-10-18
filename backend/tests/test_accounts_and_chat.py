import uuid

from fastapi.testclient import TestClient

from app.main import app


def test_register_login_and_chat_flow(monkeypatch) -> None:
    async def fake_chat(self, model, messages, tools=None):  # noqa: ANN001
        return {"message": {"role": "assistant", "content": "Hello from Forge."}}

    monkeypatch.setattr("app.chat_api.OllamaClient.chat", fake_chat)
    email = f"forge-{uuid.uuid4().hex[:8]}@example.com"

    with TestClient(app) as client:
        register = client.post(
            "/auth/register",
            json={"email": email, "password": "password123", "display_name": "Forge"},
        )
        assert register.status_code == 201
        token = register.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        me = client.get("/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["email"] == email

        denied = client.get("/chat/sessions")
        assert denied.status_code == 401

        reply = client.post("/chat/messages", headers=headers, json={"content": "Hi"})
        assert reply.status_code == 200
        payload = reply.json()
        assert payload["session"]["id"] > 0
        assert payload["messages"][-1]["content"] == "Hello from Forge."

        sessions = client.get("/chat/sessions", headers=headers)
        assert sessions.status_code == 200
        assert len(sessions.json()) == 1


def test_duplicate_register_rejected() -> None:
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
    with TestClient(app) as client:
        body = {"email": email, "password": "password123", "display_name": "Dup"}
        assert client.post("/auth/register", json=body).status_code == 201
        assert client.post("/auth/register", json=body).status_code == 409
