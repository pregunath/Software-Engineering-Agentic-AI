from app.models import TaskStatus


class InvalidTaskTransition(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.QUEUED: {TaskStatus.PLANNING, TaskStatus.CANCELLED},
    TaskStatus.PLANNING: {TaskStatus.AWAITING_APPROVAL, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.AWAITING_APPROVAL: {TaskStatus.EXECUTING, TaskStatus.CANCELLED},
    TaskStatus.EXECUTING: {TaskStatus.TESTING, TaskStatus.NEEDS_ATTENTION, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.TESTING: {TaskStatus.EXECUTING, TaskStatus.COMPLETED, TaskStatus.NEEDS_ATTENTION, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.NEEDS_ATTENTION: {TaskStatus.EXECUTING, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


def transition_task(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidTaskTransition(f"Cannot transition task from '{current}' to '{target}'")
    return target
