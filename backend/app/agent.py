from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.events import record_event
from app.llm import LLMError
from app.models import PlanStatus, Task, TaskPlan, TaskStatus
from app.runtime import DuplicateWorkerError, task_runtime_registry
from app.task_service import TaskCancelled, ensure_task_continuable, update_task_status


class PlanningError(RuntimeError):
    pass


class ChatProvider(Protocol):
    async def chat(self, model: str, messages: list[dict[str, str]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]: ...

    async def model_capabilities(self, model: str) -> Any: ...


class GeneratedPlan(BaseModel):
    summary: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=20_000)
    proposed_diff: str = Field(default="", max_length=100_000)


def parse_generated_plan(response: dict[str, Any]) -> GeneratedPlan:
    message = response.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise PlanningError("Ollama returned no plan content")
    cleaned = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    try:
        payload = json.loads(cleaned)
        return GeneratedPlan.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        raise PlanningError("Ollama returned a malformed structured plan") from error


class AgentOrchestrator:
    def __init__(self, provider: ChatProvider, model: str, db: Session, repository_context: str = "") -> None:
        self.provider = provider
        self.model = model
        self.db = db
        self.repository_context = repository_context[:50_000]

    async def generate_plan(self, task_id: int) -> TaskPlan:
        task = self.db.get(Task, task_id)
        if task is None:
            raise PlanningError("Task not found")
        if self.db.query(TaskPlan).filter(TaskPlan.task_id == task_id).one_or_none() is not None:
            raise PlanningError("Task already has a plan")
        if task.status == TaskStatus.QUEUED.value:
            update_task_status(self.db, task_id, TaskStatus.PLANNING)
        elif task.status != TaskStatus.PLANNING.value:
            raise PlanningError("Task is not available for planning")

        try:
            runtime = task_runtime_registry.begin(task_id, "planning")
        except DuplicateWorkerError as error:
            raise PlanningError(str(error)) from error

        try:
            ensure_task_continuable(self.db, task_id, {TaskStatus.PLANNING})
            capabilities = await self.provider.model_capabilities(self.model)
            if runtime.cancel_event.is_set():
                raise TaskCancelled(f"Task {task_id} was cancelled")
            record_event(
                self.db,
                task_id,
                "agent.model_ready",
                {"model": self.model, "tools": bool(getattr(capabilities, "supports_tools", False))},
            )
            self.db.commit()

            response = await self.provider.chat(
                self.model,
                [
                    {
                        "role": "system",
                        "content": "Return only JSON with summary, content, and proposed_diff. Do not edit files or run commands.",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Task title: {task.title}\n"
                            f"Task description: {task.description}\n"
                            f"Repository context:\n{self.repository_context or 'No repository context was supplied.'}"
                        ),
                    },
                ],
            )

            # Delayed model responses must not restart cancelled work.
            ensure_task_continuable(self.db, task_id, {TaskStatus.PLANNING})
            plan_input = parse_generated_plan(response)
            ensure_task_continuable(self.db, task_id, {TaskStatus.PLANNING})
        except TaskCancelled as error:
            record_event(self.db, task_id, "agent.planning_cancelled", {"detail": str(error)})
            self.db.commit()
            raise PlanningError(str(error)) from error
        except (LLMError, PlanningError) as error:
            try:
                ensure_task_continuable(self.db, task_id, {TaskStatus.PLANNING})
            except TaskCancelled:
                record_event(self.db, task_id, "agent.planning_cancelled", {"detail": str(error)})
                self.db.commit()
                raise PlanningError(f"Task {task_id} was cancelled") from error
            record_event(self.db, task_id, "agent.planning_failed", {"detail": str(error)})
            self.db.commit()
            update_task_status(self.db, task_id, TaskStatus.FAILED)
            raise PlanningError(str(error)) from error
        finally:
            task_runtime_registry.end(task_id)

        update_task_status(self.db, task_id, TaskStatus.AWAITING_APPROVAL)
        plan = TaskPlan(
            task_id=task_id,
            summary=plan_input.summary,
            content=plan_input.content,
            proposed_diff=plan_input.proposed_diff,
            status=PlanStatus.AWAITING_APPROVAL.value,
        )
        self.db.add(plan)
        self.db.flush()
        record_event(self.db, task_id, "plan.created", {"plan_id": plan.id, "source": "ollama"})
        self.db.commit()
        self.db.refresh(plan)
        return plan
