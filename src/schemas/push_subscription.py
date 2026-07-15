# src/schemas/push_subscription.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PushSubscriptionKeys(BaseModel):
    """Соответствует форме PushSubscriptionJSON.keys из браузерного Push API."""

    p256dh: str
    auth: str


class PushSubscriptionCreate(BaseModel):
    """
    Соответствует результату `PushSubscription.toJSON()` в браузере —
    фронтенд передаёт этот объект как есть, без преобразований.
    """

    endpoint: str = Field(..., max_length=2000)
    keys: PushSubscriptionKeys


class PushSubscriptionUnsubscribe(BaseModel):
    endpoint: str


class PushSubscriptionSchema(BaseModel):
    id: int
    endpoint: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
