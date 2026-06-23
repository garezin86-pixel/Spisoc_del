from pydantic import BaseModel, Field, model_validator
from datetime import datetime
from typing import Literal
from src.models.task import TaskPriority

VisibilityType = Literal["private", "group", "global"]


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
    visibility: VisibilityType = "private"
    group_id: int | None = None
    items: list[TemplateItemCreate] = []

    @model_validator(mode="after")
    def validate_group(self):
        if self.visibility == "group" and not self.group_id:
            raise ValueError("group_id обязателен при visibility=group")
        if self.visibility != "group":
            self.group_id = None
        return self


class TemplateUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    visibility: VisibilityType | None = None
    group_id: int | None = None
    items: list[TemplateItemCreate] | None = None

    @model_validator(mode="after")
    def validate_group(self):
        if self.visibility == "group" and not self.group_id:
            raise ValueError("group_id обязателен при visibility=group")
        if self.visibility and self.visibility != "group":
            self.group_id = None
        return self


class TemplateGroupResponse(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class TemplateResponse(BaseModel):
    id: int
    title: str
    description: str | None
    owner_id: int
    visibility: str
    group_id: int | None
    group: TemplateGroupResponse | None
    created_at: datetime
    items: list[TemplateItemResponse]

    model_config = {"from_attributes": True}


class ApplyTemplateRequest(BaseModel):
    project_id: int
