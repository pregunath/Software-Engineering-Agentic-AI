from pathlib import Path

from app.repository_inspection import RepositoryInspector


def test_planner_context_uses_bounded_inspection(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=hidden", encoding="utf-8")

    inspector = RepositoryInspector(tmp_path)
    context = "\n".join(inspector.list_files())

    assert "main.py" in context
    assert ".env" not in context
