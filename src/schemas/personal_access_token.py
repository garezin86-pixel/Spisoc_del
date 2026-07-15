# src/schemas/personal_access_token.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PersonalAccessTokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Название для опознания токена в списке")
    expires_in_days: int | None = Field(
        default=None, ge=1, le=3650, description="Срок жизни в днях. Не указано — токен бессрочный."
    )


class PersonalAccessTokenSchema(BaseModel):
    """Без token_hash и без самого токена — только метаданные для списка."""

    id: int
    name: str
    token_prefix: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class PersonalAccessTokenCreatedResponse(PersonalAccessTokenSchema):
    """
    Единственный ответ, где полный токен виден в открытом виде — только
    в момент создания. Дальше он нигде не восстановим (хранится лишь хэш).
    """

    token: str
