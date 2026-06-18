# src/schemas/schemas_audit.py
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime, timezone
import zoneinfo

USER_TZ = zoneinfo.ZoneInfo("Europe/Kiev")


def _fmt_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(USER_TZ).strftime("%d.%m.%Y %H:%M:%S")


ACTION_LABELS = {
    "create": "Создана",
    "update": "Изменена",
    "delete": "Удалена",
    "restore": "Восстановлена",
}

ACTION_ICONS = {
    "create": "✅",
    "update": "✏️",
    "delete": "🗑",
    "restore": "♻️",
}

FIELD_LABELS = {
    "title": "Заголовок",
    "description": "Описание",
    "is_done": "Статус",
    "status": "Статус",
    "deadline": "Дедлайн",
    "user_id": "Исполнитель",
    "group_id": "Группа",
    "priority": "Приоритет",
    "project_id": "Проект",
    "deleted_at": "Удалена",
}


class AuditUserSchema(BaseModel):
    id: int
    username: str
    model_config = ConfigDict(from_attributes=True)


class AuditLogSchema(BaseModel):
    id: int
    action: str
    action_label: str
    action_icon: str
    user: Optional[AuditUserSchema] = None
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None
    changed_at: Optional[str] = None
    field_labels: dict = {}

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_model(cls, entry) -> "AuditLogSchema":
        # Человекочитаемые названия полей для changed fields
        fields = {}
        if entry.new_values:
            for key in entry.new_values:
                fields[key] = FIELD_LABELS.get(key, key)

        return cls(
            id=entry.id,
            action=(
                entry.action.value if hasattr(entry.action, "value") else entry.action
            ),
            action_label=ACTION_LABELS.get(
                entry.action.value if hasattr(entry.action, "value") else entry.action,
                str(entry.action) if entry.action is not None else "",
            ),
            action_icon=ACTION_ICONS.get(
                entry.action.value if hasattr(entry.action, "value") else entry.action,
                "📝",
            ),
            user=(
                AuditUserSchema(id=entry.user.id, username=entry.user.username)
                if entry.user
                else None
            ),
            old_values=entry.old_values,
            new_values=entry.new_values,
            changed_at=_fmt_dt(entry.changed_at),
            field_labels=fields,
        )
