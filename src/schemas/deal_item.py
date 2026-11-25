# src/schemas/deal_item.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.schemas.deal import Money


def _name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Название оборудования не может быть пустым")
    return v


class DealItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Название оборудования (свободный текст)")
    price: Optional[Money] = Field(None, description="Цена в валюте сделки; вводится вручную, можно не указывать")

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return _name(v)


class DealItemUpdate(BaseModel):
    """PATCH: меняются только переданные поля. `price: null` очищает цену."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    price: Optional[Money] = None

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        if v is None:
            raise ValueError("Название нельзя очистить")
        return _name(v)


class DealItemSchema(BaseModel):
    id: int
    deal_id: int
    name: str
    price: Optional[Money] = None
    currency: Optional[str] = None  # валюта сделки
    position: int = 0
    author_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
