# src/services/activity_service.py
"""Глобальная лента активности ("Timeline").

Отдельной инфраструктуры не потребовалось: задачи и комментарии уже пишут
свою историю изменений в audit_log через AuditMixin (см. src/models/audit.py).
Этот сервис просто читает эти записи через AuditRepository, обогащает их
названиями задач/превью комментариев и человекочитаемым описанием
изменившихся полей — и отдаёт в виде, готовом для рендера на фронтенде
(без сырых old_values/new_values).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.task_labels import PRIORITY_LABELS, STATUS_LABELS
from src.models.audit import AuditAction, AuditLog
from src.models.comment import CommentModel
from src.models.task import SpisokModel
from src.repositories.audit_repository import AuditRepository

# Человекочитаемые названия полей — только для тех, что реально имеет смысл
# показывать в ленте. Остальные изменившиеся поля просто выводятся как есть.
_FIELD_LABELS = {
    "title": "название",
    "description": "описание",
    "status": "статус",
    "priority": "приоритет",
    "deadline": "дедлайн",
    "user_id": "исполнитель",
    "project_id": "проект",
    "group_id": "группа",
    "recurrence_rule": "повторение",
}


def _humanize_value(field: str, value) -> str:
    if value is None:
        return "—"
    if field == "status":
        return STATUS_LABELS.get(value, str(value))
    if field == "priority":
        return PRIORITY_LABELS.get(value, str(value))
    return str(value)


class ActivityService:
    def __init__(self, audit_repo: AuditRepository, session: AsyncSession):
        self.audit_repo = audit_repo
        self.session = session

    async def get_feed(self, offset: int = 0, limit: int = 50) -> tuple[list[dict], int]:
        entries, total = await self.audit_repo.get_global_feed(offset=offset, limit=limit)
        if not entries:
            return [], total

        task_ids: set[int] = set()
        comment_ids: set[int] = set()
        for entry in entries:
            if entry.entity_type == "spisok_del":
                task_ids.add(entry.entity_id)
            elif entry.entity_type == "comments":
                comment_ids.add(entry.entity_id)

        comments_by_id: dict[int, CommentModel] = {}
        if comment_ids:
            result = await self.session.execute(select(CommentModel).where(CommentModel.id.in_(comment_ids)))
            comments_by_id = {c.id: c for c in result.scalars().all()}
            task_ids.update(c.task_id for c in comments_by_id.values())

        titles_by_task_id: dict[int, str] = {}
        if task_ids:
            result = await self.session.execute(
                select(SpisokModel.id, SpisokModel.title).where(SpisokModel.id.in_(task_ids))
            )
            titles_by_task_id = {row[0]: row[1] for row in result.all()}

        feed = [self._build_item(entry, comments_by_id, titles_by_task_id) for entry in entries]
        return feed, total

    def _build_item(
        self,
        entry: AuditLog,
        comments_by_id: dict[int, CommentModel],
        titles_by_task_id: dict[int, str],
    ) -> dict:
        task_id: int | None = None
        task_title: str | None = None
        comment_preview: str | None = None

        if entry.entity_type == "spisok_del":
            task_id = entry.entity_id
            task_title = titles_by_task_id.get(task_id, "(задача удалена)")
        elif entry.entity_type == "comments":
            comment = comments_by_id.get(entry.entity_id)
            if comment is not None:
                task_id = comment.task_id
                task_title = titles_by_task_id.get(task_id, "(задача удалена)")
                comment_preview = comment.content[:140]

        return {
            "id": entry.id,
            "action": entry.action.value,
            "entity_type": entry.entity_type,
            "changed_at": entry.changed_at,
            "user_id": entry.user_id,
            "username": entry.user.username if entry.user else None,
            "task_id": task_id,
            "task_title": task_title,
            "comment_preview": comment_preview,
            "changes": self._describe_changes(entry),
        }

    @staticmethod
    def _describe_changes(entry: AuditLog) -> list[dict]:
        """[{field, label, old, new}] изменившихся полей — только для action=update."""
        if entry.action != AuditAction.update or not entry.new_values:
            return []
        changes = []
        for field, new_value in entry.new_values.items():
            old_value = (entry.old_values or {}).get(field)
            changes.append(
                {
                    "field": field,
                    "label": _FIELD_LABELS.get(field, field),
                    "old": _humanize_value(field, old_value),
                    "new": _humanize_value(field, new_value),
                }
            )
        return changes
