from pydantic import BaseModel, Field
from datetime import datetime
from src.models.task import TaskPriority


class TemplateItemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    priority: TaskPriority = TaskPriority.medium
    order_index: int = 0


class TemplateItemResponse(BaseModel):
    id: int
    title: str
    priority: TaskPriority
    order_index: int

    model_config = {"from_attributes": True}


class TemplateCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    items: list[TemplateItemCreate] = []


class TemplateUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    items: list[TemplateItemCreate] | None = None


class TemplateResponse(BaseModel):
    id: int
    title: str
    description: str | None
    owner_id: int
    created_at: datetime
    items: list[TemplateItemResponse]

    model_config = {"from_attributes": True}


class ApplyTemplateRequest(BaseModel):
    project_id: int
