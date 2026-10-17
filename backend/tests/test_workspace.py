from pathlib import Path

import pytest

from app.workspace import WorkspaceError, WorkspaceManager


def test_create_copy_excludes_git_dependencies_and_secrets(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "node_modules").mkdir()
    (source / ".env").write_text("SECRET=hidden", encoding="utf-8")
    (source / "main.py").write_text("print('ok')", encoding="utf-8")

    workspace = WorkspaceManager(tmp_path / "copies").create_copy(source)

    assert workspace.path != source
    assert (workspace.path / "main.py").read_text(encoding="utf-8") == "print('ok')"
    assert not (workspace.path / ".git").exists()
    assert not (workspace.path / "node_modules").exists()
    assert not (workspace.path / ".env").exists()


def test_source_cannot_contain_workspace_storage(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    manager = WorkspaceManager(source / ".workspaces")

    with pytest.raises(WorkspaceError, match="inside"):
        manager.create_copy(source)
