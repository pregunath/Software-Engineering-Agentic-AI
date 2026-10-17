import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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


def test_register_list_tree_read_write_and_traversal(tmp_path: Path) -> None:
    source = tmp_path / "project"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (source / ".env").write_text("SECRET=1\n", encoding="utf-8")

    with configured_app(AGENT_ALLOW_HOST_WORKSPACES="true", AGENT_API_KEY="") as app:
        with TestClient(app) as client:
            caps = client.get("/repos/capabilities")
            assert caps.status_code == 200
            assert caps.json()["host_workspaces_enabled"] is True

            created = client.post("/repos", json={"path": str(source), "name": "demo"})
            assert created.status_code == 201
            repo_id = created.json()["id"]

            listed = client.get("/repos")
            assert listed.status_code == 200
            assert listed.json()[0]["id"] == repo_id

            tree = client.get(f"/repos/{repo_id}/tree")
            assert tree.status_code == 200
            files = tree.json()["files"]
            assert "src/app.py" in files
            assert ".env" not in files

            read = client.get(f"/repos/{repo_id}/file", params={"path": "src/app.py"})
            assert read.status_code == 200
            assert "hello" in read.json()["content"]

            stale = client.put(
                f"/repos/{repo_id}/file",
                json={
                    "path": "src/app.py",
                    "content": "print('new')\n",
                    "expected_content": "wrong",
                },
            )
            assert stale.status_code == 409

            saved = client.put(
                f"/repos/{repo_id}/file",
                json={
                    "path": "src/app.py",
                    "content": "print('new')\n",
                    "expected_content": "print('hello')\n",
                },
            )
            assert saved.status_code == 200
            assert (source / "src" / "app.py").read_text(encoding="utf-8") == "print('new')\n"

            escape = client.get(f"/repos/{repo_id}/file", params={"path": "../outside.txt"})
            assert escape.status_code == 400

            agent = client.post(f"/repos/{repo_id}/agent-workspace")
            assert agent.status_code == 200
            assert Path(agent.json()["path"]).is_dir()


def test_host_workspaces_can_be_disabled(tmp_path: Path) -> None:
    source = tmp_path / "project"
    source.mkdir()
    with configured_app(AGENT_ALLOW_HOST_WORKSPACES="false", AGENT_API_KEY="") as app:
        with TestClient(app) as client:
            response = client.post("/repos", json={"path": str(source)})
            assert response.status_code == 403
            caps = client.get("/repos/capabilities")
            assert caps.json()["host_workspaces_enabled"] is False
