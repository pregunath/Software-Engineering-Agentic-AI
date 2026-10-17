from pathlib import Path
from difflib import unified_diff

import pytest

from app.execution import ExecutionError, SafeCommandRunner
from app.patching import FileChange, PatchError, WorkspaceEditor


def test_changes_are_checkpointed_and_can_be_rolled_back(tmp_path: Path) -> None:
    target = tmp_path / "main.py"
    target.write_text("old\n", encoding="utf-8")
    editor = WorkspaceEditor(tmp_path)

    checkpoint = editor.apply_changes([FileChange("main.py", "old\n", "new\n")])
    assert target.read_text(encoding="utf-8") == "new\n"

    editor.rollback(checkpoint)
    assert target.read_text(encoding="utf-8") == "old\n"


def test_stale_expected_content_rejects_and_restores(tmp_path: Path) -> None:
    target = tmp_path / "main.py"
    target.write_text("current\n", encoding="utf-8")
    editor = WorkspaceEditor(tmp_path)

    with pytest.raises(PatchError, match="changed since inspection"):
        editor.apply_changes([FileChange("main.py", "stale\n", "new\n")])
    assert target.read_text(encoding="utf-8") == "current\n"


def test_unified_diff_is_validated_and_applied_with_checkpoint(tmp_path: Path) -> None:
    target = tmp_path / "main.py"
    target.write_text("old\nkeep\n", encoding="utf-8")
    diff = "".join(
        unified_diff(
            ["old\n", "keep\n"],
            ["new\n", "keep\n"],
            fromfile="a/main.py",
            tofile="b/main.py",
        )
    )

    checkpoint = WorkspaceEditor(tmp_path).apply_unified_diff(diff)

    assert target.read_text(encoding="utf-8") == "new\nkeep\n"
    assert checkpoint.files == ("main.py",)


def test_unified_diff_rejects_traversal(tmp_path: Path) -> None:
    target = tmp_path / "main.py"
    target.write_text("old\n", encoding="utf-8")
    diff = "--- a/../main.py\n+++ b/../main.py\n@@ -1 +1 @@\n-old\n+new\n"

    with pytest.raises(PatchError):
        WorkspaceEditor(tmp_path).apply_unified_diff(diff)


def test_command_allowlist_runs_an_approved_command(tmp_path: Path) -> None:
    runner = SafeCommandRunner(tmp_path)

    result = runner.run(["python", "-m", "pytest", "--version"])

    assert result.exit_code == 0
    assert "pytest" in result.stdout.lower()


def test_command_allowlist_rejects_arbitrary_commands(tmp_path: Path) -> None:
    runner = SafeCommandRunner(tmp_path)

    with pytest.raises(ExecutionError, match="allowlist"):
        runner.run(["python", "-c", "print('not allowed')"])
