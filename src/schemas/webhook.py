# src/schemas/webhook.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.enums import WebhookEvent


def _validate_url(v: str) -> str:
    if not (v.startswith("http://") or v.startswith("https://")):
        raise ValueError("URL должен начинаться с http:// или https://")
    return v


class WebhookCreate(BaseModel):
    url: str = Field(..., max_length=2000, description="Куда слать POST-запрос при наступлении события")
    events: list[WebhookEvent] = Field(
        ..., min_length=1, description="Хотя бы одно событие — иначе вебхук никогда не сработает"
    )
    is_active: bool = True

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        return _validate_url(v)


class WebhookUpdate(BaseModel):
    """Все поля опциональны — PATCH меняет только переданное."""

    url: str | None = Field(default=None, max_length=2000)
    events: list[WebhookEvent] | None = Field(default=None, min_length=1)
    is_active: bool | None = None

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_url(v)


class WebhookSchema(BaseModel):
    """Без secret — только secret_prefix, чтобы владелец опознал вебхук в списке."""

    id: int
    url: str
    secret_prefix: str
    events: list[WebhookEvent]
    is_active: bool
    created_at: datetime
    last_triggered_at: datetime | None
    last_status_code: int | None
    last_error: str | None
    failure_count: int

    model_config = ConfigDict(from_attributes=True)


class WebhookCreatedResponse(WebhookSchema):
    """Единственный ответ, где виден полный secret — сохраните сразу, повторно не восстановим."""

    secret: str


class WebhookSecretRotatedResponse(BaseModel):
    """Ответ на регенерацию секрета — тоже единственный раз в открытом виде."""

    id: int
    secret: str
    secret_prefix: str


class WebhookTestResult(BaseModel):
    """Результат ручной тестовой отправки — быстрая проверка, что endpoint настроен верно."""

    delivered: bool
    status_code: int | None
    error: str | None
