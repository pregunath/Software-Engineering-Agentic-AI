import pytest

from app.models import TaskStatus
from app.state_machine import InvalidTaskTransition, transition_task


def test_task_can_progress_through_approval_to_completion() -> None:
    assert transition_task(TaskStatus.QUEUED, TaskStatus.PLANNING) == TaskStatus.PLANNING
    assert transition_task(TaskStatus.PLANNING, TaskStatus.AWAITING_APPROVAL) == TaskStatus.AWAITING_APPROVAL
    assert transition_task(TaskStatus.AWAITING_APPROVAL, TaskStatus.EXECUTING) == TaskStatus.EXECUTING
    assert transition_task(TaskStatus.EXECUTING, TaskStatus.TESTING) == TaskStatus.TESTING
    assert transition_task(TaskStatus.TESTING, TaskStatus.COMPLETED) == TaskStatus.COMPLETED


def test_task_cannot_skip_approval_or_reopen_completed_task() -> None:
    with pytest.raises(InvalidTaskTransition):
        transition_task(TaskStatus.QUEUED, TaskStatus.EXECUTING)
    with pytest.raises(InvalidTaskTransition):
        transition_task(TaskStatus.COMPLETED, TaskStatus.EXECUTING)
