# src/schemas/deal.py
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from src.models.deal import StageKind

# Сумма: в БД Decimal (точные деньги), в JSON — обычное число.
Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=14, decimal_places=2),
    PlainSerializer(lambda v: float(v), return_type=float, when_used="json"),
]


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _title(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Название не может быть пустым")
    return v


# ── воронка ──────────────────────────────────────────────────────────────────
class StageSchema(BaseModel):
    id: int
    name: str
    position: int
    kind: StageKind

    model_config = ConfigDict(from_attributes=True)


class PipelineSchema(BaseModel):
    id: int
    name: str
    stages: list[StageSchema]


class StageCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    kind: StageKind = StageKind.open
    position: Optional[int] = Field(None, ge=0)  # с нуля; остальные сдвигаются. Не передана — в конец

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return _title(v)


class StageUpdate(BaseModel):
    """Тип стадии (kind) после создания не меняется."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    position: Optional[int] = Field(None, ge=0)

    @field_validator("name", "position")
    @classmethod
    def _not_null(cls, v):
        if v is None:
            raise ValueError("Поле нельзя очистить")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return _title(v)


# ── сделки ───────────────────────────────────────────────────────────────────
class DealCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    amount: Optional[Money] = None
    owner_id: Optional[int] = None  # не передан — создатель; назначать другого может admin/manager
    expected_close_date: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=5000)
    stage_id: Optional[int] = None  # не передана — первая открытая стадия

    @field_validator("title")
    @classmethod
    def _t(cls, v):
        return _title(v)

    @field_validator("notes")
    @classmethod
    def _n(cls, v):
        return _clean(v)


class DealUpdate(BaseModel):
    """PATCH. Справочные поля (title, notes): ответственный, admin, manager.
    Процессные (amount, owner_id, expected_close_date): только admin и manager.
    Стадия меняется отдельно: POST /deals/{id}/move."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    notes: Optional[str] = Field(None, max_length=5000)
    amount: Optional[Money] = None
    owner_id: Optional[int] = None
    expected_close_date: Optional[date] = None

    @field_validator("title")
    @classmethod
    def _t(cls, v):
        if v is None:
            raise ValueError("Название нельзя очистить")
        return _title(v)

    @field_validator("notes")
    @classmethod
    def _n(cls, v):
        return _clean(v)


class DealMove(BaseModel):
    stage_id: int
    lost_reason: Optional[str] = Field(None, max_length=500)  # обязательна для стадии вида lost

    @field_validator("lost_reason")
    @classmethod
    def _r(cls, v):
        return _clean(v)


class DealSchema(BaseModel):
    id: int
    client_id: int
    stage_id: int
    title: str
    amount: Optional[Money] = None
    owner_id: Optional[int] = None
    expected_close_date: Optional[date] = None
    closed_at: Optional[datetime] = None
    lost_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
