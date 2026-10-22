# src/schemas/ai.py
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AIScreenContext(BaseModel):
    """Что открыто на экране: пока только карточка клиента («создай задачу позвонить завтра» — про него)."""

    client_id: int | None = Field(default=None, ge=1)


class AIMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    context: AIScreenContext | None = None

    @field_validator("text")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Текст команды пустой")
        return value


class AIConfirmIn(BaseModel):
    pending_id: str = Field(min_length=1, max_length=64)
    confirm: bool


class AIChooseIn(BaseModel):
    pending_id: str = Field(min_length=1, max_length=64)
    option_id: int


class AIOption(BaseModel):
    id: int
    label: str


class AIPendingOut(BaseModel):
    """Решение, которого ждёт ассистент: подтвердить действие или выбрать вариант."""

    id: str
    kind: Literal["confirm", "choose"]
    text: str
    options: list[AIOption] = []


class AIAction(BaseModel):
    """Команда интерфейсу, которую исполняет веб-панель (например, открыть карточку клиента)."""

    type: Literal["open_client"]
    client_id: int


class AIReply(BaseModel):
    messages: list[str]
    actions: list[AIAction] = []
    pending: AIPendingOut | None = None
    changed: bool = False  # True — после «да» действие выполнено: интерфейсу пора обновить данные
