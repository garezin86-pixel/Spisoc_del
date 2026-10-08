# src/schemas/client.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clean(value: Optional[str]) -> Optional[str]:
    """Обрезает пробелы; пустая строка → None."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _check_email(value: Optional[str]) -> Optional[str]:
    value = _clean(value)
    if value is not None and ("@" not in value or value.startswith("@") or value.endswith("@")):
        raise ValueError("Некорректный email")
    return value


class ClientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=5000)
    # Ответственный. Не передан — станет создатель. Назначать другого может admin/manager.
    owner_id: Optional[int] = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v

    @field_validator("phone", "address", "notes")
    @classmethod
    def _strip(cls, v):
        return _clean(v)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return _check_email(v)


class ClientUpdate(BaseModel):
    """PATCH: меняются только переданные поля; null очищает необязательное поле."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=5000)
    owner_id: Optional[int] = None

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        if v is None:
            raise ValueError("Название нельзя очистить")
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v

    @field_validator("phone", "address", "notes")
    @classmethod
    def _strip(cls, v):
        return _clean(v)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return _check_email(v)


class ClientSchema(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    owner_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    position: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = Field(None, max_length=5000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Имя не может быть пустым")
        return v

    @field_validator("position", "phone", "notes")
    @classmethod
    def _strip(cls, v):
        return _clean(v)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return _check_email(v)


class ContactUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    position: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = Field(None, max_length=5000)

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        if v is None:
            raise ValueError("Имя нельзя очистить")
        v = v.strip()
        if not v:
            raise ValueError("Имя не может быть пустым")
        return v

    @field_validator("position", "phone", "notes")
    @classmethod
    def _strip(cls, v):
        return _clean(v)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return _check_email(v)


class ContactSchema(BaseModel):
    id: int
    client_id: int
    name: str
    position: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
