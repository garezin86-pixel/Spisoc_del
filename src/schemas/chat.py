# src/schemas/chat.py
from datetime import datetime

from pydantic import BaseModel, Field


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    group_id: int | None = Field(None, description="Канал группы. Не задано — общий канал.")


class ChatMessageResponse(BaseModel):
    id: int
    user_id: int
    username: str
    group_id: int | None = None
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatChannel(BaseModel):
    """Один пункт в списке доступных пользователю каналов чата."""

    group_id: int | None  # None — общий канал
    name: str
