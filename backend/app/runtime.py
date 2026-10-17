from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field


class DuplicateWorkerError(RuntimeError):
    pass


@dataclass
class TaskRuntime:
    task_id: int
    phase: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    process: subprocess.Popen[str] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class TaskRuntimeRegistry:
    """In-process registry linking cancellation intent to active workers and Docker processes."""

    def __init__(self) -> None:
        self._runtimes: dict[int, TaskRuntime] = {}
        self._lock = threading.Lock()

    def begin(self, task_id: int, phase: str) -> TaskRuntime:
        with self._lock:
            existing = self._runtimes.get(task_id)
            if existing is not None:
                raise DuplicateWorkerError(f"Task {task_id} already has an active worker in phase '{existing.phase}'")
            runtime = TaskRuntime(task_id=task_id, phase=phase)
            self._runtimes[task_id] = runtime
            return runtime

    def end(self, task_id: int) -> None:
        with self._lock:
            self._runtimes.pop(task_id, None)

    def get(self, task_id: int) -> TaskRuntime | None:
        with self._lock:
            return self._runtimes.get(task_id)

    def is_cancel_requested(self, task_id: int) -> bool:
        runtime = self.get(task_id)
        return runtime is not None and runtime.cancel_event.is_set()

    def attach_process(self, task_id: int, process: subprocess.Popen[str]) -> None:
        runtime = self.get(task_id)
        if runtime is None:
            return
        with runtime.lock:
            runtime.process = process

    def clear_process(self, task_id: int) -> None:
        runtime = self.get(task_id)
        if runtime is None:
            return
        with runtime.lock:
            runtime.process = None

    def request_cancel(self, task_id: int, terminate_timeout_seconds: float = 5.0) -> dict[str, object]:
        """Signal cancellation and attempt to stop any attached process owned by this task."""
        runtime = self.get(task_id)
        if runtime is None:
            return {
                "worker_active": False,
                "process_terminated": None,
                "cleanup_timed_out": False,
            }
        runtime.cancel_event.set()
        with runtime.lock:
            process = runtime.process
        if process is None or process.poll() is not None:
            return {
                "worker_active": True,
                "process_terminated": None,
                "cleanup_timed_out": False,
            }
        process.terminate()
        try:
            process.wait(timeout=terminate_timeout_seconds)
            return {
                "worker_active": True,
                "process_terminated": True,
                "cleanup_timed_out": False,
            }
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=terminate_timeout_seconds)
                return {
                    "worker_active": True,
                    "process_terminated": True,
                    "cleanup_timed_out": True,
                }
            except subprocess.TimeoutExpired:
                return {
                    "worker_active": True,
                    "process_terminated": False,
                    "cleanup_timed_out": True,
                }

    def clear(self) -> None:
        with self._lock:
            self._runtimes.clear()


task_runtime_registry = TaskRuntimeRegistry()
