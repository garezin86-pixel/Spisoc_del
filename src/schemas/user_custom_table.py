# src/schemas/user_custom_table.py
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.schemas.custom_field import _name, _options

UserTableVisibilityName = Literal["private", "shared", "restricted"]
UserTableColumnTypeName = Literal["text", "number", "date", "boolean", "select", "client", "deal", "user"]

MAX_COLUMNS_PER_TABLE = 50


class UserTableColumnCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    data_type: UserTableColumnTypeName = Field(
        ...,
        description="Тип нельзя изменить после создания. client, deal, user — связь с записью CRM или пользователем "
        "(одна связь на ячейку, значение — id)",
    )
    options: Optional[list[str]] = Field(None, description="Допустимые значения; только для типа select")

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return _name(v)

    @model_validator(mode="after")
    def _check_options(self):
        if self.data_type == "select":
            self.options = _options(self.options or [])
        elif self.options is not None:
            raise ValueError("Значения списка задаются только для типа select")
        return self


class UserTableColumnUpdate(BaseModel):
    """PATCH: название, значения списка, порядок. Тип и ключ не меняются."""

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


class UserTableColumnSchema(BaseModel):
    id: int
    key: str = Field(..., description="Стабильный ключ c<id>: не меняется при переименовании")
    name: str
    data_type: str
    options: Optional[list[str]] = None
    position: int = 0

    model_config = ConfigDict(from_attributes=True)


def _clean_optional_text(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v or None


class UserTableCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    icon: Optional[str] = Field(None, max_length=16, description="Эмодзи")
    visibility: UserTableVisibilityName = Field(
        "shared",
        description="private — владелец, admin, manager; shared — вся компания; "
        "restricted — плюс выбранные пользователи (участники)",
    )
    columns: list[UserTableColumnCreate] = Field(default_factory=list, max_length=MAX_COLUMNS_PER_TABLE)

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return _name(v)

    @field_validator("description", "icon")
    @classmethod
    def _t(cls, v):
        return _clean_optional_text(v)

    @model_validator(mode="after")
    def _unique_columns(self):
        seen: set[str] = set()
        for col in self.columns:
            key = col.name.casefold()
            if key in seen:
                raise ValueError(f"Колонка «{col.name}» повторяется")
            seen.add(key)
        return self


class UserTableUpdate(BaseModel):
    """PATCH: меняются только переданные поля. `owner_id` может менять только admin или manager."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)  # null или пустая строка очищает
    icon: Optional[str] = Field(default=None, max_length=16)  # null или пустая строка очищает
    visibility: Optional[UserTableVisibilityName] = None
    owner_id: Optional[int] = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        if v is None:
            raise ValueError("Название нельзя очистить")
        return _name(v)

    @field_validator("description", "icon")
    @classmethod
    def _t(cls, v):
        return _clean_optional_text(v)

    @field_validator("visibility", "owner_id")
    @classmethod
    def _required(cls, v):
        if v is None:
            raise ValueError("Значение нельзя очистить")
        return v


class UserTableListItem(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    visibility: str
    owner_id: Optional[int] = None
    columns_count: int = 0
    can_edit_rows: bool = Field(True, description="Может ли текущий пользователь менять строки")
    can_manage: bool = Field(False, description="Может ли менять структуру, настройки и участников")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserTableSchema(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    visibility: str
    owner_id: Optional[int] = None
    can_edit_rows: bool = Field(True, description="Может ли текущий пользователь менять строки")
    can_manage: bool = Field(False, description="Может ли менять структуру, настройки и участников")
    columns: list[UserTableColumnSchema] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserTableRowCreate(BaseModel):
    """Новая строка. `values` — значения по ключам колонок (`c<id>`); не переданные колонки остаются пустыми.
    Пустая строка (без значений) допустима."""

    values: dict[str, Any] = Field(default_factory=dict, max_length=MAX_COLUMNS_PER_TABLE)


class UserTableRowUpdate(BaseModel):
    """Правка строки: меняются только переданные колонки, `null` (или пустая строка) очищает значение.
    `version` — `updated_at` из последнего ответа: если строку с тех пор меняли, будет 409. Без `version` правка
    применяется как есть (побеждает последняя запись)."""

    values: dict[str, Any] = Field(default_factory=dict, max_length=MAX_COLUMNS_PER_TABLE)
    version: Optional[str] = Field(default=None, max_length=64)


class UserTableRowSchema(BaseModel):
    id: int
    values: dict[str, Any] = Field(description="Значения по ключам живых колонок (c<id>); пусто — null")
    created_by_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = Field(None, description="Версия строки: передавайте как `version` при правке")


class UserTableRowsPage(BaseModel):
    items: list[UserTableRowSchema]
    total: int
    page: int
    size: int
    pages: int


MAX_TABLE_MEMBERS = 100


class UserTableMemberInput(BaseModel):
    user_id: int = Field(..., ge=1)
    can_edit: bool = Field(True, description="false — участник только читает таблицу")


class UserTableMembersUpdate(BaseModel):
    """Полный список участников: те, кого нет в списке, теряют доступ."""

    members: list[UserTableMemberInput] = Field(default_factory=list, max_length=MAX_TABLE_MEMBERS)

    @model_validator(mode="after")
    def _unique_users(self):
        seen: set[int] = set()
        for member in self.members:
            if member.user_id in seen:
                raise ValueError(f"Пользователь {member.user_id} указан дважды")
            seen.add(member.user_id)
        return self


class UserTableMemberSchema(BaseModel):
    user_id: int
    username: Optional[str] = None
    can_edit: bool = True
