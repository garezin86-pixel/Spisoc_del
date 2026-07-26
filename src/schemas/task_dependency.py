# src/schemas/task_dependency.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.models.enums import TaskStatus


class TaskDependencyCreate(BaseModel):
    blocker_task_id: int = Field(..., description="Задача, которая должна закрыться раньше текущей")


class TaskRefSchema(BaseModel):
    """Минимальная информация о задаче — для списков блокеров/заблокированных, без всех полей SpisokSchema."""

    id: int
    title: str
    status: TaskStatus

    model_config = ConfigDict(from_attributes=True)


class TaskDependenciesSchema(BaseModel):
    blockers: list[TaskRefSchema] = Field(description="Задачи, которые блокируют текущую (должны закрыться раньше)")
    blocked: list[TaskRefSchema] = Field(description="Задачи, которые ждут закрытия текущей")


class TaskDependencySchema(BaseModel):
    id: int
    blocker_task_id: int
    blocked_task_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
