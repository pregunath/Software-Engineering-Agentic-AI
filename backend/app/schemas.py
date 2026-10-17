from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import TaskStatus


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=20_000)
    workspace_id: int | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    status: TaskStatus
    workspace_id: int | None = None
    created_at: datetime
    updated_at: datetime


class TaskStatusUpdate(BaseModel):
    status: TaskStatus


class PlanCreate(BaseModel):
    summary: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=20_000)
    proposed_diff: str = Field(default="", max_length=100_000)


class PlanGenerateRequest(BaseModel):
    workspace_path: str | None = Field(default=None, max_length=1_000)
    open_file_path: str | None = Field(default=None, max_length=500)
    selection: str | None = Field(default=None, max_length=20_000)


class ExecutionRequest(BaseModel):
    workspace_path: str = Field(min_length=1, max_length=1_000)


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    summary: str
    content: str
    proposed_diff: str
    status: str
    created_at: datetime
    approved_at: datetime | None
