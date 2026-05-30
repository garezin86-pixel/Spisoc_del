from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    field_serializer,
    model_validator,
)
from typing import Optional
from enum import Enum
from datetime import datetime, timezone
import zoneinfo

from src.schemas.group import GroupSchema
from src.schemas.user import UserSchemaForTask

USER_TZ = zoneinfo.ZoneInfo("Europe/Kiev")


class SpisokAddSchema(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    is_done: bool = False
    deadline: Optional[datetime] = None

    user_id: Optional[int] = Field(default=None, ge=1)
    group_id: Optional[int] = Field(default=None, ge=1)

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
    is_done: bool = False
    deadline: Optional[datetime] = None
    user_id: Optional[int] = Field(None, ge=1)
    group_id: Optional[int] = Field(None, ge=1)

    author: UserSchemaForTask | None
    user: UserSchemaForTask | None
    group: GroupSchema | None

    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at", "updated_at", "deadline")
    def serialize_dt(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(USER_TZ).strftime("%d.%m.%Y %H:%M")


class SpisokUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    is_done: Optional[bool] = None
    deadline: Optional[datetime] = None

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
    is_done: bool
    deadline: datetime | None
    author: UserSchemaForTask | None
    user: UserSchemaForTask | None
    group: GroupSchema | None
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
