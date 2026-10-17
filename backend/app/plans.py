from fastapi import APIRouter, Depends, HTTPException, status
from pathlib import Path
from sqlalchemy.orm import Session

from app.agent import AgentOrchestrator, PlanningError
from app.config import Settings, get_settings
from app.execution_service import execute_approved_plan
from app.db import get_db
from app.events import record_event
from app.models import PlanStatus, Task, TaskPlan, TaskStatus
from app.ollama import OllamaClient
from app.repository_inspection import InspectionError, RepositoryInspector
from app.schemas import ExecutionRequest, PlanCreate, PlanGenerateRequest, PlanRead, TaskRead
from app.task_service import approve_plan, update_task_status

router = APIRouter(prefix="/tasks", tags=["plans"])


@router.post("/{task_id}/plan", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
def create_plan(task_id: int, plan_input: PlanCreate, db: Session = Depends(get_db)) -> TaskPlan:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if db.query(TaskPlan).filter(TaskPlan.task_id == task_id).one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Task already has a plan")
    if task.status == TaskStatus.QUEUED.value:
        update_task_status(db, task_id, TaskStatus.PLANNING)
    if task.status in {TaskStatus.QUEUED.value, TaskStatus.PLANNING.value}:
        update_task_status(db, task_id, TaskStatus.AWAITING_APPROVAL)
    elif task.status != TaskStatus.AWAITING_APPROVAL.value:
        raise HTTPException(status_code=409, detail="Task cannot receive a plan in its current state")
    plan = TaskPlan(
        task_id=task_id,
        summary=plan_input.summary,
        content=plan_input.content,
        proposed_diff=plan_input.proposed_diff,
        status=PlanStatus.AWAITING_APPROVAL.value,
    )
    db.add(plan)
    db.flush()
    record_event(db, task_id, "plan.created", {"plan_id": plan.id})
    db.commit()
    db.refresh(plan)
    return plan


@router.post("/{task_id}/plan/generate", response_model=PlanRead)
async def generate_task_plan(
    task_id: int,
    request: PlanGenerateRequest | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TaskPlan:
    repository_context = ""
    if request and request.workspace_path:
        try:
            inspector = RepositoryInspector(Path(request.workspace_path))
            repository_context = "FILES:\n" + "\n".join(inspector.list_files())
            configuration = inspector.inspect_project_configuration()
            repository_context += "\n\nCONFIGURATION:\n" + "\n".join(
                f"{name}:\n{content}" for name, content in configuration.items()
            )
            if request.open_file_path:
                try:
                    open_content = inspector.read_file(request.open_file_path)
                    repository_context += (
                        f"\n\nOPEN_FILE ({request.open_file_path}):\n{open_content[:12_000]}"
                    )
                except InspectionError:
                    pass
            if request.selection:
                repository_context += f"\n\nSELECTION:\n{request.selection[:8_000]}"
        except InspectionError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    try:
        return await AgentOrchestrator(
            OllamaClient(settings), settings.ollama_model, db, repository_context
        ).generate_plan(task_id)
    except PlanningError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/{task_id}/plan", response_model=PlanRead)
def get_plan(task_id: int, db: Session = Depends(get_db)) -> TaskPlan:
    plan = db.query(TaskPlan).filter(TaskPlan.task_id == task_id).one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.post("/{task_id}/plan/approve", response_model=PlanRead)
def approve_task_plan(task_id: int, db: Session = Depends(get_db)) -> TaskPlan:
    return approve_plan(db, task_id)


@router.post("/{task_id}/execute", response_model=TaskRead)
def execute_task(task_id: int, request: ExecutionRequest, db: Session = Depends(get_db)) -> Task:
    return execute_approved_plan(db, task_id, request.workspace_path)
