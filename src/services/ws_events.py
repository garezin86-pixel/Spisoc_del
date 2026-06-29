"""
src/services/ws_events.py

Высокоуровневые функции рассылки событий через WebSocket.
Вызываются из роутеров после мутаций.
"""

from src.core.ws_manager import ws_manager
from src.models.task import SpisokModel


def _task_payload(task: SpisokModel) -> dict:
    """Минимальный payload задачи для обновления UI без перезагрузки."""
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value if task.status else None,
        "priority": task.priority.value if task.priority else None,
        "user_id": task.user_id,
        "author_id": task.author_id,
        "group_id": task.group_id,
        "project_id": task.project_id,
        "deadline": task.deadline.isoformat() if task.deadline else None,
    }


def _affected_users(task: SpisokModel) -> list[int]:
    """Список user_id которые должны получить событие по задаче."""
    users = set()
    if task.user_id:
        users.add(task.user_id)
    if task.author_id:
        users.add(task.author_id)
    return list(users)


async def emit_task_created(task: SpisokModel) -> None:
    await ws_manager.broadcast_to_users(
        _affected_users(task),
        "task_created",
        _task_payload(task),
    )


async def emit_task_updated(task: SpisokModel, changed_fields: dict | None = None) -> None:
    payload = _task_payload(task)
    if changed_fields:
        payload["changed"] = list(changed_fields.keys())
    await ws_manager.broadcast_to_users(
        _affected_users(task),
        "task_updated",
        payload,
    )


async def emit_task_deleted(task: SpisokModel) -> None:
    await ws_manager.broadcast_to_users(
        _affected_users(task),
        "task_deleted",
        {"id": task.id},
    )


async def emit_task_restored(task: SpisokModel) -> None:
    await ws_manager.broadcast_to_users(
        _affected_users(task),
        "task_restored",
        _task_payload(task),
    )


async def emit_kanban_moved(task: SpisokModel) -> None:
    """Специальное событие для канбана — обновляет только колонку."""
    await ws_manager.broadcast_to_users(
        _affected_users(task),
        "kanban_moved",
        {"id": task.id, "status": task.status.value if task.status else None},
    )


async def emit_comment_added(task: SpisokModel, comment_data: dict) -> None:
    await ws_manager.broadcast_to_users(
        _affected_users(task),
        "comment_added",
        {"task_id": task.id, "comment": comment_data},
    )
