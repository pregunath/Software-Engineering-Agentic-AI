import pytest

from app.agent import AgentOrchestrator, PlanningError, parse_generated_plan
from app.db import SessionLocal, initialize_database
from app.models import Task, TaskStatus


class FakeCapabilities:
    supports_tools = False


class FakeProvider:
    async def model_capabilities(self, model: str) -> FakeCapabilities:
        return FakeCapabilities()

    async def chat(self, model: str, messages, tools=None) -> dict[str, object]:
        return {
            "message": {
                "role": "assistant",
                "content": '{"summary":"Fix parser","content":"Inspect parser and update tests.","proposed_diff":""}',
            }
        }


@pytest.mark.asyncio
async def test_orchestrator_persists_ollama_plan_for_approval() -> None:
    initialize_database()
    db = SessionLocal()
    try:
        task = Task(title="Planner task", description="Find the parser issue.", status=TaskStatus.QUEUED.value)
        db.add(task)
        db.commit()
        db.refresh(task)
        plan = await AgentOrchestrator(FakeProvider(), "test-model", db).generate_plan(task.id)
        db.refresh(task)
        assert plan.summary == "Fix parser"
        assert plan.status == "awaiting_approval"
        assert task.status == TaskStatus.AWAITING_APPROVAL.value
    finally:
        db.close()


def test_malformed_plan_is_rejected() -> None:
    with pytest.raises(PlanningError, match="malformed"):
        parse_generated_plan({"message": {"content": "not json"}})
