# src/schemas/custom_field.py
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CustomEntityType = Literal["client", "deal"]
CustomFieldTypeName = Literal["text", "number", "date", "select", "boolean"]

MAX_OPTIONS = 50
MAX_OPTION_LENGTH = 100


def _name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Название поля не может быть пустым")
    return v


def _options(values: list[str]) -> list[str]:
    """Значения списка: без пустых и повторов (повтор — даже если отличается только регистром)."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        v = raw.strip()
        if not v:
            raise ValueError("Значение списка не может быть пустым")
        if len(v) > MAX_OPTION_LENGTH:
            raise ValueError(f"Значение списка не длиннее {MAX_OPTION_LENGTH} символов")
        key = v.casefold()
        if key in seen:
            raise ValueError(f"Значение «{v}» повторяется")
        seen.add(key)
        cleaned.append(v)
    if not cleaned:
        raise ValueError("Укажите хотя бы одно значение списка")
    if len(cleaned) > MAX_OPTIONS:
        raise ValueError(f"Значений в списке не больше {MAX_OPTIONS}")
    return cleaned


class CustomFieldCreate(BaseModel):
    entity_type: CustomEntityType = Field(..., description="client — поле клиента, deal — поле сделки")
    name: str = Field(..., min_length=1, max_length=100)
    field_type: CustomFieldTypeName = Field(..., description="Тип нельзя изменить после создания")
    options: Optional[list[str]] = Field(None, description="Допустимые значения; только для типа select")

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return _name(v)

    @model_validator(mode="after")
    def _check_options(self):
        if self.field_type == "select":
            self.options = _options(self.options or [])
        elif self.options is not None:
            raise ValueError("Значения списка задаются только для типа select")
        return self


class CustomFieldUpdate(BaseModel):
    """PATCH: название, значения списка, порядок. Тип и сущность не меняются."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    options: Optional[list[str]] = None
    position: Optional[int] = Field(default=None, ge=0, le=1000)

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        if v is None:
            raise ValueError("Название нельзя очистить")
        return _name(v)

    @field_validator("options")
    @classmethod
    def _o(cls, v):
        if v is None:
            raise ValueError("Значения списка нельзя очистить")
        return _options(v)

    @field_validator("position")
    @classmethod
    def _p(cls, v):
        if v is None:
            raise ValueError("Порядок нельзя очистить")
        return v


class CustomFieldSchema(BaseModel):
    id: int
    entity_type: str
    name: str
    field_type: str
    options: Optional[list[str]] = None
    position: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CustomValueSet(BaseModel):
    """Значение поля. `null` очищает. Тип проверяется по типу поля: text/select — строка, number — число,
    date — «YYYY-MM-DD», boolean — true/false."""

    value: Any = None


class CustomValueSchema(BaseModel):
    field_id: int
    entity_id: int
    value: Any = None
