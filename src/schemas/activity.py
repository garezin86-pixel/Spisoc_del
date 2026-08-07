# src/schemas/activity.py
from datetime import datetime

from pydantic import BaseModel


class ActivityChange(BaseModel):
    field: str
    label: str
    old: str
    new: str


class ActivityFeedItem(BaseModel):
    id: int
    action: str  # "create" | "update" | "delete" | "restore"
    entity_type: str  # "spisok_del" | "comments"
    changed_at: datetime
    user_id: int | None
    username: str | None
    task_id: int | None
    task_title: str | None
    comment_preview: str | None
    changes: list[ActivityChange]

    model_config = {"from_attributes": True}
