# src/schemas/deal.py
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from src.models.deal import DEFAULT_CURRENCY, SUPPORTED_CURRENCIES, StageKind

# Сумма: в БД Decimal (точные деньги), в JSON — обычное число.
Money = Annotated[
    Decimal,
    Field(ge=0, max_digits=14, decimal_places=2),
    PlainSerializer(lambda v: float(v), return_type=float, when_used="json"),
]


def _currency(v: Optional[str]) -> Optional[str]:
    if v is None:
        raise ValueError("Валюту нельзя очистить")
    v = v.strip().upper()
    if v not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Валюта должна быть одной из: {', '.join(SUPPORTED_CURRENCIES)}")
    return v


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _color(v: Optional[str]) -> Optional[str]:
    """ "#RRGGBB" → "#rrggbb"; None / пусто — без своего цвета."""
    if v is None or v.strip() == "":
        return None
    v = v.strip()
    if not _HEX_COLOR.match(v):
        raise ValueError("Цвет должен быть в формате #rrggbb")
    return v.lower()


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


# Итоговая сумма: без ограничения разрядов (сумма многих сделок может быть больше одной), в JSON — число
MoneyTotal = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


class CurrencyTotal(BaseModel):
    """Сделки одной валюты: количество и сумма (сделки без суммы считаются в count, в amount не входят)."""

    currency: str
    count: int
    amount: MoneyTotal


class StageSummary(BaseModel):
    stage_id: int
    name: str
    kind: StageKind
    color: Optional[str] = None
    position: int
    count: int
    totals: list[CurrencyTotal]  # по валютам; суммы разных валют не складываются


class KindSummary(BaseModel):
    count: int
    totals: list[CurrencyTotal]


class ConversionSummary(BaseModel):
    """Конверсия считается по сделкам, уже ушедшим в успех или отказ: win_rate = won / (won + lost)."""

    open: int
    won: int
    lost: int
    closed: int
    win_rate: Optional[float] = None  # 0..1; None, пока нет ни одной закрытой сделки


class PipelineSummary(BaseModel):
    pipeline_id: int
    pipeline_name: str
    stages: list[StageSummary]
    by_kind: dict[StageKind, KindSummary]
    conversion: ConversionSummary


# ── воронка ──────────────────────────────────────────────────────────────────
class StageSchema(BaseModel):
    id: int
    name: str
    position: int
    kind: StageKind
    color: Optional[str] = None  # "#rrggbb" или None — цвет по виду стадии

    model_config = ConfigDict(from_attributes=True)


class PipelineSchema(BaseModel):
    id: int
    name: str
    stages: list[StageSchema]


class PipelineListItem(PipelineSchema):
    """Воронка в списке: со стадиями и числом живых сделок."""

    deals_count: int = 0


class PipelineCreate(BaseModel):
    """Новая воронка. Без copy_from_id — минимальная (Новая → Успех / Отказ), со ссылкой — копия стадий той воронки."""

    name: str = Field(..., min_length=1, max_length=100)
    copy_from_id: Optional[int] = None

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return _title(v)


class PipelineUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return _title(v)


class StageCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    kind: StageKind = StageKind.open
    position: Optional[int] = Field(None, ge=0)  # с нуля; остальные сдвигаются. Не передана — в конец
    pipeline_id: Optional[int] = None  # не передан — воронка по умолчанию (первая)
    color: Optional[str] = None  # "#rrggbb"

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return _title(v)

    @field_validator("color")
    @classmethod
    def _c(cls, v):
        return _color(v)


class StageUpdate(BaseModel):
    """Тип стадии (kind) после создания не меняется."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    position: Optional[int] = Field(None, ge=0)
    color: Optional[str] = None  # "#rrggbb"; null — сбросить на цвет по виду стадии

    @field_validator("color")
    @classmethod
    def _c(cls, v):
        return _color(v)

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
    currency: Optional[str] = None  # не передана — UAH
    owner_id: Optional[int] = None  # не передан — создатель; назначать другого может admin/manager
    expected_close_date: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=5000)
    pipeline_id: Optional[int] = None  # воронка для новой сделки; не передана — воронка по умолчанию
    stage_id: Optional[int] = None  # не передана — первая открытая стадия выбранной воронки

    @field_validator("title")
    @classmethod
    def _t(cls, v):
        return _title(v)

    @field_validator("notes")
    @classmethod
    def _n(cls, v):
        return _clean(v)

    @field_validator("currency")
    @classmethod
    def _c(cls, v):
        return _currency(v)


class DealUpdate(BaseModel):
    """PATCH. Справочные поля (title, notes): ответственный, admin, manager.
    Процессные (amount, currency, owner_id, expected_close_date): только admin и manager.
    Стадия меняется отдельно: POST /deals/{id}/move."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    notes: Optional[str] = Field(None, max_length=5000)
    amount: Optional[Money] = None
    currency: Optional[str] = None
    owner_id: Optional[int] = None
    expected_close_date: Optional[date] = None

    @field_validator("currency")
    @classmethod
    def _c(cls, v):
        return _currency(v)

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
    """PATCH /deals/{id}/stage. position — с нуля внутри целевой колонки (остальные сдвигаются);
    не передана — в конец колонки. Тот же stage_id + position — перестановка внутри колонки."""

    stage_id: int
    position: Optional[int] = Field(None, ge=0)
    lost_reason: Optional[str] = Field(None, max_length=500)  # обязательна для стадии вида lost

    @field_validator("lost_reason")
    @classmethod
    def _r(cls, v):
        return _clean(v)


class DealSchema(BaseModel):
    id: int
    client_id: int
    client_name: Optional[str] = None  # имя клиента (название компании или ФИО)
    client_type: Optional[str] = None  # "company" (B2B) | "person" (B2C)
    stage_id: int
    title: str
    amount: Optional[Money] = None
    currency: str = DEFAULT_CURRENCY
    owner_id: Optional[int] = None
    expected_close_date: Optional[date] = None
    closed_at: Optional[datetime] = None
    lost_reason: Optional[str] = None
    notes: Optional[str] = None
    position: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DealStageChange(BaseModel):
    """Одна смена стадии в истории сделки (из аудита)."""

    id: int
    changed_at: datetime
    user_id: Optional[int] = None
    username: Optional[str] = None
    from_stage_id: Optional[int] = None
    from_stage_name: Optional[str] = None
    to_stage_id: Optional[int] = None
    to_stage_name: Optional[str] = None
    lost_reason: Optional[str] = None
