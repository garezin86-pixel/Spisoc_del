# src/schemas/scheduled_event.py
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.scheduled_event import EventStatus, EventType


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


class EventCreate(BaseModel):
    type: EventType
    starts_at: datetime
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    title: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=5000)
    contact_id: Optional[int] = None
    assignee_id: Optional[int] = None  # не передан — текущий пользователь

    @field_validator("starts_at")
    @classmethod
    def _starts(cls, v):
        return _aware(v)

    @field_validator("title", "notes")
    @classmethod
    def _text(cls, v):
        return _clean(v)


class EventUpdate(BaseModel):
    """PATCH: меняются только переданные поля.

    Статус: planned (вернуть) или cancelled; done — только через /complete.
    """

    type: Optional[EventType] = None
    starts_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    title: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=5000)
    contact_id: Optional[int] = None
    assignee_id: Optional[int] = None
    status: Optional[EventStatus] = None

    @field_validator("type", "starts_at", "assignee_id", "status")
    @classmethod
    def _not_null(cls, v):
        if v is None:
            raise ValueError("Поле нельзя очистить")
        return v

    @field_validator("starts_at")
    @classmethod
    def _starts(cls, v):
        return _aware(v)

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v == EventStatus.done:
            raise ValueError("Завершить событие можно только через POST /events/{id}/complete")
        return v

    @field_validator("title", "notes")
    @classmethod
    def _text(cls, v):
        return _clean(v)


class EventComplete(BaseModel):
    """Итог состоявшейся встречи/звонка — станет summary взаимодействия."""

    summary: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("summary")
    @classmethod
    def _summary(cls, v):
        return _clean(v)


class EventSchema(BaseModel):
    id: int
    client_id: int
    client_name: Optional[str] = None  # заполняется в списках и ответах API: календарю не нужен запрос за клиентом
    contact_id: Optional[int] = None
    type: EventType
    title: Optional[str] = None
    starts_at: datetime
    duration_minutes: Optional[int] = None
    assignee_id: Optional[int] = None
    status: EventStatus
    notes: Optional[str] = None
    completed_interaction_id: Optional[int] = None
    created_by_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
