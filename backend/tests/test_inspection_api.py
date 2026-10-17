from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_inspection_api_lists_and_reads_workspace_files(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("def greet():\n    return 'hello'\n", encoding="utf-8")

    with TestClient(app) as client:
        files = client.post("/inspection/files", json={"workspace_path": str(tmp_path)})
        content = client.post(
            "/inspection/file",
            json={"workspace_path": str(tmp_path), "path": "main.py"},
        )
        matches = client.post(
            "/inspection/search",
            json={"workspace_path": str(tmp_path), "query": "hello"},
        )

    assert files.status_code == 200
    assert files.json()["files"] == ["main.py"]
    assert content.json()["content"].startswith("def greet")
    assert matches.json()["results"][0]["line"] == 2


def test_inspection_api_rejects_path_escape(tmp_path: Path) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/inspection/file",
            json={"workspace_path": str(tmp_path), "path": "../outside.txt"},
        )

    assert response.status_code == 400
    assert "escapes" in response.json()["detail"]
