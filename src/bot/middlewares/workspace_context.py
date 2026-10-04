# src/bot/middlewares/workspace_context.py
"""Привязывает каждый апдейт Telegram к workspace отправителя.

Зачем: хендлеры бота открывают сессии БД сами (`UnitOfWork(get_session_maker())`),
причём часто несколько раз за один апдейт — например, check_admin() узнаёт
пользователя в одной сессии, а действие («список пользователей»,
«заблокировать по id») выполняется уже в новой. Без привязки такая новая
сессия видит ВСЕ компании, и админ одной компании мог бы читать и блокировать
пользователей другой. Вместо правки каждого хендлера workspace один раз
кладётся в контекст (см. src/db/tenant_scope.py:workspace_context), а
фильтр чтения и автозаполнение записи подхватывают его для любой сессии.

Регистрируется как outer-middleware на dp.update: покрывает и сообщения, и
нажатия inline-кнопок (CallbackQuery), и всё остальное — AuthMiddleware висит
только на dp.message.
"""

from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy import select

from src.db import get_session_maker
from src.db.tenant_scope import workspace_context
from src.models.user import UserModel
from src.models.workspace import WorkspaceModel

logger = structlog.get_logger()

WORKSPACE_DISABLED_TEXT = "⛔ Аккаунт вашей компании отключён.\nОбратитесь к администратору сервиса."


class WorkspaceContextMiddleware(BaseMiddleware):
    @staticmethod
    async def _deny(event: TelegramObject, telegram_id: int, workspace_id: int) -> None:
        await logger.awarning(
            "bot_update_denied_workspace_disabled", telegram_id=telegram_id, workspace_id=workspace_id
        )
        try:
            callback = getattr(event, "callback_query", None)
            message = getattr(event, "message", None)
            if callback is not None:
                await callback.answer(WORKSPACE_DISABLED_TEXT, show_alert=True)
            elif message is not None:
                await message.answer(WORKSPACE_DISABLED_TEXT)
        except Exception:  # noqa: BLE001 — ответ необязателен, главное — не вызвать хендлер
            pass

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        tg_user: User | None = data.get("event_from_user")
        workspace_id = None
        if tg_user is not None:
            async with get_session_maker()() as session:  # без привязки: workspace ещё неизвестен
                row = (
                    await session.execute(
                        select(UserModel.workspace_id, WorkspaceModel.is_active)
                        .join(WorkspaceModel, WorkspaceModel.id == UserModel.workspace_id)
                        .where(UserModel.telegram_id == tg_user.id)
                    )
                ).first()
            if row is not None:
                workspace_id = row.workspace_id
                if not row.is_active:
                    # Компания отключена: ни команды, ни кнопки не обрабатываем. Апдейт
                    # покрывает и сообщения, и callback — отдельных обходов нет.
                    await self._deny(event, tg_user.id, workspace_id)
                    return None

        # Незарегистрированный пользователь (например, переходит по ссылке-приглашению)
        # остаётся без привязки: его workspace определит сам токен приглашения.
        with workspace_context(workspace_id):
            return await handler(event, data)
