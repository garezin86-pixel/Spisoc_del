import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
)

from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.models.task import TaskStatus
from src.repositories.groups_repository import GroupRepository
from src.repositories.tag_repository import TagRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.schemas.task import SpisokUpdate
from src.services.notifications import notify_task_updated
from src.services.task_service import TaskService

logger = logging.getLogger(__name__)

router = Router(name="notification_actions")


def make_task_service(uow: UnitOfWork) -> TaskService:
    return TaskService(
        task_repo=TaskRepository(uow.session),
        user_repo=UserRepository(uow.session),
        group_repo=GroupRepository(uow.session),
        tag_repo=TagRepository(uow.session),
        session=uow.session,  # передаём сессию в сервис для soft delete и audit
    )


# ── ✅ Выполнено ─────────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("notif_done_"))
async def notif_done_callback(callback: CallbackQuery):
    if callback.data is None:
        return

    await callback.answer()

    task_id = int(callback.data.split("_")[-1])

    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(callback.from_user.id)
        if not isinstance(callback.message, Message):
            return
        if not user:
            await callback.message.answer("❌ Пользователь не найден")
            return

        try:
            await make_task_service(uow).update_task_status(task_id, TaskStatus.done, user)
            await uow.commit()
        except Exception as e:
            await callback.message.answer(f"❌ Ошибка: {e}")
            return

    await notify_task_updated(task_id, {"status": "done"}, editor_telegram_id=callback.from_user.id)

    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Задача #{task_id} отмечена как выполненная!")


# ── ⏳ Отложить на 1 час ─────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("notif_snooze_"))
async def notif_snooze_callback(callback: CallbackQuery):
    if callback.data is None:
        return
    await callback.answer()

    task_id = int(callback.data.split("_")[-1])
    new_deadline = datetime.now(timezone.utc) + timedelta(hours=1)

    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(callback.from_user.id)
        if not isinstance(callback.message, Message):
            return
        if not user:
            await callback.message.answer("❌ Пользователь не найден")
            return

        try:
            await make_task_service(uow).update_task(task_id, SpisokUpdate(deadline=new_deadline), user)
            await uow.commit()
        except Exception as e:
            await callback.message.answer(f"❌ Ошибка: {e}")
            return

    await notify_task_updated(task_id, {"deadline": new_deadline}, editor_telegram_id=callback.from_user.id)

    deadline_str = new_deadline.strftime("%d.%m.%Y %H:%M")

    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)

    await callback.message.answer(f"⏳ Задача #{task_id} отложена. Новый дедлайн: {deadline_str} UTC")


# ── 💬 Комментировать ────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("notif_comment_"))
async def notif_comment_callback(callback: CallbackQuery, state: FSMContext):
    if callback.data is None:
        return
    await callback.answer()

    task_id = int(callback.data.split("_")[-1])

    # Проверяем что пользователь существует
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(callback.from_user.id)
        if not isinstance(callback.message, Message):
            return
        if not user:
            await callback.message.answer("❌ Пользователь не найден")
            return

    # Сохраняем task_id в FSM и переводим в состояние AddComment
    from src.bot.handlers.tasks import AddComment

    await state.update_data(task_id=task_id)
    await state.set_state(AddComment.comment_text)

    from src.bot.keyboards.main import cancel_keyboard

    await callback.message.answer(
        f"💬 Введите комментарий к задаче #{task_id}:",
        reply_markup=cancel_keyboard(),
    )
