# src/schemas/interaction.py
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.interaction import InteractionType

# Допуск на расхождение часов клиента и сервера.
_FUTURE_TOLERANCE = timedelta(minutes=5)


def _check_not_future(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    if value > datetime.now(timezone.utc) + _FUTURE_TOLERANCE:
        raise ValueError("Дата взаимодействия не может быть в будущем")
    return value


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


class InteractionCreate(BaseModel):
    type: InteractionType
    occurred_at: Optional[datetime] = None  # не передана — «сейчас»
    summary: Optional[str] = Field(None, max_length=5000)
    contact_id: Optional[int] = None

    @field_validator("occurred_at")
    @classmethod
    def _occurred(cls, v):
        return None if v is None else _check_not_future(v)

    @field_validator("summary")
    @classmethod
    def _summary(cls, v):
        return _clean(v)


class InteractionUpdate(BaseModel):
    """PATCH: меняются только переданные поля.

    Процессные поля (type, occurred_at) может менять только admin/manager;
    справочные (summary, contact_id) — ещё автор и ответственный за клиента.
    """

    type: Optional[InteractionType] = None
    occurred_at: Optional[datetime] = None
    summary: Optional[str] = Field(None, max_length=5000)
    contact_id: Optional[int] = None

    @field_validator("type", "occurred_at")
    @classmethod
    def _not_null(cls, v):
        if v is None:
            raise ValueError("Поле нельзя очистить")
        return v

    @field_validator("occurred_at")
    @classmethod
    def _occurred(cls, v):
        return _check_not_future(v)

    @field_validator("summary")
    @classmethod
    def _summary(cls, v):
        return _clean(v)


class InteractionSchema(BaseModel):
    id: int
    client_id: int
    contact_id: Optional[int] = None
    type: InteractionType
    occurred_at: datetime
    summary: Optional[str] = None
    author_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
