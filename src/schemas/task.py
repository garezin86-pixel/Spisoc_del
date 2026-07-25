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

from src.models.enums import RecurrenceRule
from src.models.task import TaskPriority, TaskStatus
from src.schemas.checklist import ChecklistItemSchema
from src.schemas.group import GroupSchema
from src.schemas.tag import TagSchema
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
    recurrence_rule: RecurrenceRule = RecurrenceRule.none

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
    recurrence_rule: RecurrenceRule = RecurrenceRule.none
    tags: list[TagSchema] = []
    checklist_items: list[ChecklistItemSchema] = []

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
    recurrence_rule: Optional[RecurrenceRule] = None

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


class TaskImportIssueSchema(BaseModel):
    """Одна построчная проблема при импорте (ошибка ИЛИ предупреждение)."""

    row: int = Field(..., description="Номер строки в исходном файле (с учётом заголовка)")
    message: str


class TaskImportSummary(BaseModel):
    """Ответ POST /tasks/import."""

    created: int
    errors: list[TaskImportIssueSchema] = []  # строки, которые не удалось создать (пропущены)
    warnings: list[TaskImportIssueSchema] = []  # строки создались, но с оговоркой (напр. дефолтный приоритет)


# ── Канбан ────────────────────────────────────────────────────────────────────


class TaskStatusUpdate(BaseModel):
    """Тело запроса PATCH /tasks/{id}/status — атомарная смена статуса."""

    status: TaskStatus


class BulkTaskUpdate(BaseModel):
    """Тело запроса PATCH /tasks/bulk.

    Нужно указать хотя бы одно из полей status/priority/tag_id/user_id —
    иначе непонятно, что вообще менять.
    """

    task_ids: list[int] = Field(..., min_length=1, max_length=200)
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    tag_id: Optional[int] = Field(
        default=None,
        ge=1,
        description="Тег добавляется к задаче, существующие теги не удаляются",
    )
    user_id: Optional[int] = Field(default=None, ge=1, description="Переназначение исполнителя (как reassign_task)")

    @model_validator(mode="after")
    def at_least_one_field(self) -> "BulkTaskUpdate":
        if all(v is None for v in (self.status, self.priority, self.tag_id, self.user_id)):
            raise ValueError("Нужно указать хотя бы одно поле для изменения: status/priority/tag_id/user_id")
        return self


class BulkTaskUpdateResult(BaseModel):
    """Ответ PATCH /tasks/bulk."""

    updated: int
    skipped: list[int] = Field(
        default_factory=list,
        description="ID задач, пропущенных: не найдены/удалены либо нет прав доступа",
    )


class KanbanResponse(BaseModel):
    """Ответ GET /tasks/kanban — задачи, сгруппированные по колонкам."""

    backlog: list[SpisokSchema] = []
    todo: list[SpisokSchema] = []
    in_progress: list[SpisokSchema] = []
    review: list[SpisokSchema] = []
    done: list[SpisokSchema] = []
