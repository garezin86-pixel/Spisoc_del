# src/schemas/notification.py
from datetime import datetime

from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: int
    notification_type: str
    task_id: int | None
    task_title: str | None
    content: str
    sent_at: datetime
    is_read: bool
    success: bool

    model_config = {"from_attributes": True}


class UnreadCount(BaseModel):
    count: int
