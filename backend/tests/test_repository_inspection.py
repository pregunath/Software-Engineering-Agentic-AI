from pathlib import Path

import pytest

from app.repository_inspection import InspectionError, RepositoryInspector


def make_workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "secrets.env").write_text("TOKEN=do-not-read\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("hidden\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.js").write_text("hidden\n", encoding="utf-8")
    return tmp_path


def test_list_files_excludes_ignored_and_secret_files(tmp_path: Path) -> None:
    inspector = RepositoryInspector(make_workspace(tmp_path))

    assert inspector.list_files() == [".gitignore", "src/main.py"]


def test_read_file_rejects_traversal_and_ignored_files(tmp_path: Path) -> None:
    inspector = RepositoryInspector(make_workspace(tmp_path))

    with pytest.raises(InspectionError, match="escapes"):
        inspector.read_file("../outside.txt")
    with pytest.raises(InspectionError, match="unavailable"):
        inspector.read_file("secrets.env")
    with pytest.raises(InspectionError, match="unavailable"):
        inspector.read_file("ignored.txt")


def test_search_code_returns_bounded_matches(tmp_path: Path) -> None:
    inspector = RepositoryInspector(make_workspace(tmp_path))

    assert inspector.search_code("hello") == [
        {"path": "src/main.py", "line": 1, "text": "print('hello')"}
    ]


def test_symlink_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    target = workspace / "src" / "main.py"
    link = workspace / "linked.py"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symbolic links are unavailable in this environment")

    with pytest.raises(InspectionError, match="Symbolic links"):
        RepositoryInspector(workspace).read_file("linked.py")
