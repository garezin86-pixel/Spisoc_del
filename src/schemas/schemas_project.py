# src/schemas/project.py
import zoneinfo
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.user import UserSchemaForTask

USER_TZ = zoneinfo.ZoneInfo("Europe/Kiev")


def _fmt_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(USER_TZ).strftime("%d.%m.%Y %H:%M")


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    group_id: Optional[int] = Field(None)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    group_id: Optional[int] = Field(None)


class ProjectGroupSchema(BaseModel):
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)


class ProjectMemberSchema(BaseModel):
    id: int
    username: str
    position: str | None = None
    model_config = ConfigDict(from_attributes=True)


class ProjectSchema(BaseModel):
    """Полная схема проекта — для списков и детального просмотра."""

    id: int
    name: str
    description: Optional[str]
    owner: UserSchemaForTask | None
    group: ProjectGroupSchema | None = None
    group_id: Optional[int] = None
    members: list[ProjectMemberSchema] = []
    task_count: int = 0
    done_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_model(cls, project) -> "ProjectSchema":
        tasks = project.tasks or []
        return cls(
            id=project.id,
            name=project.name,
            description=project.description,
            owner=project.owner,
            members=[ProjectMemberSchema(id=u.id, username=u.username) for u in (project.members or [])],
            group=(ProjectGroupSchema(id=project.group.id, name=project.group.name) if project.group else None),
            group_id=project.group_id,
            task_count=len(tasks),
            done_count=sum(1 for t in tasks if t.status and t.status.value == "done"),
            created_at=_fmt_dt(project.created_at),
            updated_at=_fmt_dt(project.updated_at),
        )


class ProjectShortSchema(BaseModel):
    """Короткая схема для вложения в задачу."""

    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)
