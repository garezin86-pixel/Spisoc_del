# src/schemas/filter_preset.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.models.enums import TaskPriority, TaskStatus
from src.schemas.task import FilterUserGroup, TaskFilter


class FilterPresetCreate(BaseModel):
    """Тело запроса POST /tasks/presets — сохраняет текущую комбинацию фильтров."""

    name: str = Field(..., min_length=1, max_length=100)
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    tag_id: Optional[int] = Field(default=None, ge=1)
    project_id: Optional[int] = Field(default=None, ge=1)
    filter_user_group: Optional[FilterUserGroup] = None
    filter_type: Optional[TaskFilter] = None


class FilterPresetSchema(BaseModel):
    """Ответ GET /tasks/presets и POST /tasks/presets."""

    id: int
    name: str
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    tag_id: Optional[int] = None
    project_id: Optional[int] = None
    filter_user_group: Optional[FilterUserGroup] = None
    filter_type: Optional[TaskFilter] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
