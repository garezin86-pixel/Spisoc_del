from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.models.task import TaskPriority, TaskStatus
from src.schemas.group import GroupSchema
from src.schemas.user import UserSchemaForTask


class SpisokAddSchema(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    deadline: Optional[datetime] = None

    user_id: Optional[int] = Field(default=None, ge=1)
    group_id: Optional[int] = Field(default=None, ge=1)
    project_id: Optional[int] = Field(default=None, ge=1)
    priority: TaskPriority = TaskPriority.medium
    status: TaskStatus = TaskStatus.todo

    @field_validator("user_id", "group_id")
    def validate_ids(cls, v):
        if v == 0:
            return None
        return v

    @field_validator("deadline")
    @classmethod
    def deadline_not_in_past(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        now = datetime.now(timezone.utc)
        # приводим к UTC если нет tzinfo
        v_utc = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if v_utc < now:
            raise ValueError("Дедлайн не может быть в прошлом")
        return v

    @model_validator(mode="after")
    def user_or_group_not_both(self) -> "SpisokAddSchema":
        if self.user_id is not None and self.group_id is not None:
            raise ValueError("Нельзя указывать одновременно user_id и group_id")
        return self


class SpisokSchema(BaseModel):
    id: int
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    deadline: Optional[datetime] = None
    user_id: Optional[int] = Field(None, ge=1)
    group_id: Optional[int] = Field(None, ge=1)

    author: UserSchemaForTask | None
    user: UserSchemaForTask | None
    group: GroupSchema | None
    project_id: Optional[int] = None
    priority: TaskPriority = TaskPriority.medium
    status: TaskStatus = TaskStatus.todo

    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class SpisokUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    deadline: Optional[datetime] = None
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None

    @field_validator("deadline")
    @classmethod
    def deadline_not_in_past(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        now = datetime.now(timezone.utc)
        v_utc = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if v_utc < now:
            raise ValueError("Дедлайн не может быть в прошлом")
        return v.replace(second=0, microsecond=0)


class TaskFilter(str, Enum):
    today = "today"
    overdue = "overdue"
    planned = "planned"
    deadline_null = "deadline_null"


class FilterUserGroup(str, Enum):
    user = "user"
    group = "group"
    free = "free"
    author = "author"


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str | None
    deadline: datetime | None
    author: UserSchemaForTask | None
    user: UserSchemaForTask | None
    group: GroupSchema | None
    project_id: Optional[int] = None
    priority: TaskPriority = TaskPriority.medium
    status: TaskStatus = TaskStatus.todo
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class TaskPriorityFilter(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


# ── Канбан ────────────────────────────────────────────────────────────────────


class TaskStatusUpdate(BaseModel):
    """Тело запроса PATCH /tasks/{id}/status — атомарная смена статуса."""

    status: TaskStatus


class KanbanResponse(BaseModel):
    """Ответ GET /tasks/kanban — задачи, сгруппированные по колонкам."""

    backlog: list[SpisokSchema] = []
    todo: list[SpisokSchema] = []
    in_progress: list[SpisokSchema] = []
    review: list[SpisokSchema] = []
    done: list[SpisokSchema] = []
