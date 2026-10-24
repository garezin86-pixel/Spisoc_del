# src/schemas/client.py
from datetime import date, datetime, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ClientType = Literal["company", "person"]  # B2B / B2C
Gender = Literal["male", "female"]


def _check_birth_date(value: Optional[date]) -> Optional[date]:
    """Дата рождения — не в будущем и не раньше 1900 года."""
    if value is not None and (value > date.today() or value < date(1900, 1, 1)):
        raise ValueError("Некорректная дата рождения")
    return value


def _check_next_contact(value: Optional[date]) -> Optional[date]:
    """Дата следующего контакта — сегодня или позже (день допуска на разницу часовых поясов)."""
    if value is not None and value < date.today() - timedelta(days=1):
        raise ValueError("Дата следующего контакта не может быть в прошлом")
    return value


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
    name: str = Field(..., min_length=1, max_length=200)  # название компании или ФИО частного лица
    client_type: ClientType = "company"
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    address: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=5000)
    # Ответственный. Не передан — станет создатель. Назначать другого может admin/manager.
    owner_id: Optional[int] = None
    birth_date: Optional[date] = None  # только для частного лица (person); в PATCH null — очистить
    gender: Optional[Gender] = None  # только для частного лица; в PATCH null — очистить
    next_contact_at: Optional[date] = None  # «связаться снова»; в PATCH null — очистить

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

    @field_validator("next_contact_at")
    @classmethod
    def _next_contact(cls, v):
        return _check_next_contact(v)

    @field_validator("birth_date")
    @classmethod
    def _birth(cls, v):
        return _check_birth_date(v)


class ClientUpdate(BaseModel):
    """PATCH: меняются только переданные поля; null очищает необязательное поле."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    client_type: Optional[ClientType] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    address: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=5000)
    owner_id: Optional[int] = None
    birth_date: Optional[date] = None  # только для частного лица (person); в PATCH null — очистить
    gender: Optional[Gender] = None  # только для частного лица; в PATCH null — очистить
    next_contact_at: Optional[date] = None  # «связаться снова»; в PATCH null — очистить

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

    @field_validator("next_contact_at")
    @classmethod
    def _next_contact(cls, v):
        return _check_next_contact(v)

    @field_validator("client_type")
    @classmethod
    def _type(cls, v):
        if v is None:
            raise ValueError("Тип клиента нельзя очистить")
        return v

    @field_validator("birth_date")
    @classmethod
    def _birth(cls, v):
        return _check_birth_date(v)


class ClientSchema(BaseModel):
    id: int
    name: str
    client_type: str = "company"
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    owner_id: Optional[int] = None
    birth_date: Optional[date] = None
    gender: Optional[str] = None
    next_contact_at: Optional[date] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ClientDetailSchema(ClientSchema):
    """Карточка клиента: плюс дата последнего взаимодействия (None, если их не было)."""

    last_interaction_at: Optional[datetime] = None


class ContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    position: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=5000)

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
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    position: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=5000)

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


# ── импорт клиентов из файла ─────────────────────────────────────────────────
class ImportIssue(BaseModel):
    row: int  # номер строки в файле (строка 1 — заголовки)
    message: str


class ImportPreviewRow(BaseModel):
    row: int
    name: str
    client_type: str
    phone: Optional[str] = None
    email: Optional[str] = None


class ClientImportReport(BaseModel):
    dry_run: bool
    default_type: str  # company / person / auto — как сервер понял «Тип, если не указан»
    total_rows: int
    to_create: int  # сколько строк годятся к созданию
    created: int  # сколько реально создано (при dry_run — 0)
    skipped_duplicates: int
    errors: list[ImportIssue]  # строка пропущена целиком
    warnings: list[ImportIssue]  # строка создаётся, но часть значений отброшена
    duplicates: list[ImportIssue]
    preview: list[ImportPreviewRow]  # первые годные строки


class ImportColumn(BaseModel):
    index: int
    header: str
    suggested: Optional[str] = None  # поле клиента, которое подсказано автоматически
    samples: list[str]


class ImportField(BaseModel):
    key: str
    label: str
    required: bool


class ClientImportColumns(BaseModel):
    columns: list[ImportColumn]
    fields: list[ImportField]
    total_rows: int
