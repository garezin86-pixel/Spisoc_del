# src/db/dashboard_invalidation.py
"""Сброс кэша дашборда и событие WebSocket `dashboard_changed` при изменениях, влияющих на дашборд (Этап 4, шаг 3).

Один слушатель на классе Session вместо правок каждого сервиса: после успешного коммита по записям, которые были
в flush, определяется, чьи дашборды затронуты, их кэш сбрасывается, а подключённым пользователям уходит
`dashboard_changed` — по нему фронт перезапрашивает `GET /dashboard`.

Кого затрагивает изменение:
- задача (`user_id`), клиент (`owner_id`), сделка (`owner_id`), событие (`assignee_id`) — этот пользователь и
  прежний, если запись переназначили;
- взаимодействие, воронка, стадия — ответственный неизвестен без запроса, поэтому вся компания.

Не покрыто: массовые UPDATE/DELETE через `session.execute(update(...))` не проходят через flush — после них кэш
живёт до конца TTL (45 с). Сброс — best-effort: ошибки Redis/WebSocket не влияют на коммит.
"""

import asyncio
from typing import Any

import structlog
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

logger = structlog.get_logger()

EVENT_NAME = "dashboard_changed"
_PENDING_KEY = "_dashboard_pending"
_ALL = "*"  # вся компания

_installed = False
_tasks: set[asyncio.Task] = set()
_rules_cache: dict[type, str | None] | None = None


def _rules() -> dict[type, str | None]:
    """Модель → поле с ответственным пользователем (None — затрагивает всю компанию). Лениво: циклические импорты."""
    global _rules_cache
    if _rules_cache is None:
        from src.models.client import ClientModel
        from src.models.deal import DealModel, PipelineModel, StageModel
        from src.models.interaction import InteractionModel
        from src.models.scheduled_event import ScheduledEventModel
        from src.models.task import SpisokModel

        _rules_cache = {
            SpisokModel: "user_id",
            ClientModel: "owner_id",
            DealModel: "owner_id",
            ScheduledEventModel: "assignee_id",
            InteractionModel: None,
            PipelineModel: None,
            StageModel: None,
        }
    return _rules_cache


def _users_of(obj: Any, field: str) -> set[int]:
    """Текущий и прежний ответственный записи."""
    users: set[int] = set()
    current = getattr(obj, field, None)
    if current is not None:
        users.add(current)
    try:
        history = inspect(obj).attrs[field].history
    except Exception:
        return users
    users.update(v for v in history.deleted if v is not None)
    return users


def _collect(session: Session, _flush_context) -> None:
    rules = _rules()
    pending: dict[Any, Any] = session.info.setdefault(_PENDING_KEY, {})
    objects = [*session.new, *(o for o in session.dirty if session.is_modified(o)), *session.deleted]
    for obj in objects:
        if type(obj) not in rules:
            continue
        workspace_id = getattr(obj, "workspace_id", None)
        field = rules[type(obj)]
        if field is None:
            pending[workspace_id] = _ALL
            continue
        if pending.get(workspace_id) == _ALL:
            continue
        pending.setdefault(workspace_id, set()).update(_users_of(obj, field))


def _discard(session: Session, *_args) -> None:
    session.info.pop(_PENDING_KEY, None)


def _schedule(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, None)
    if not pending:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # синхронный контекст (скрипты, миграции): отправлять некуда
    task = loop.create_task(_notify(pending))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _notify(pending: dict[Any, Any]) -> None:
    from src.core.ws_manager import ws_manager
    from src.utils.dashboard_cache import dashboard_cache

    for workspace_id, who in pending.items():
        try:
            if who == _ALL:
                if workspace_id is not None:
                    await dashboard_cache.invalidate_workspace(workspace_id)
                await ws_manager.broadcast_all(EVENT_NAME, {}, workspace_id=workspace_id)
            elif who:
                if workspace_id is not None:
                    for user_id in who:
                        await dashboard_cache.invalidate_user(workspace_id, user_id)
                await ws_manager.broadcast_to_users(sorted(who), EVENT_NAME, {})
        except Exception as exc:  # уведомление не критично
            await logger.awarning("dashboard_notify_failed", workspace_id=workspace_id, error=str(exc))


async def wait_idle() -> None:
    """Дождаться отправленных уведомлений (для тестов и корректного завершения)."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
        await asyncio.sleep(0)  # дать отработать done-callback'ам, иначе цикл крутится вхолостую


def install_dashboard_invalidation() -> None:
    """Идемпотентно вешает слушатели на класс Session (как install_tenant_autofill)."""
    global _installed
    if _installed:
        return
    event.listen(Session, "after_flush", _collect)
    event.listen(Session, "after_commit", _schedule)
    event.listen(Session, "after_rollback", _discard)
    event.listen(Session, "after_soft_rollback", _discard)
    _installed = True
