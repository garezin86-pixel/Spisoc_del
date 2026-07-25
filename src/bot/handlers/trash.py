from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from src.bot.keyboards.main import (
    main_menu_admin,
    main_menu_user,
    trash_keyboard,
)
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.models.user import UserRole
from src.repositories.groups_repository import GroupRepository
from src.repositories.tag_repository import TagRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.services.task_service import TaskService
from src.utils.datetime_utils import to_local

router = Router()

PAGE_SIZE = 5


def make_task_service(uow: UnitOfWork) -> TaskService:
    return TaskService(
        task_repo=TaskRepository(uow.session),
        user_repo=UserRepository(uow.session),
        group_repo=GroupRepository(uow.session),
        tag_repo=TagRepository(uow.session),
        session=uow.session,
    )


class TrashMenu(StatesGroup):
    browsing = State()  # просмотр списка корзины
    restore_id = State()  # ввод ID для восстановления
    hard_delete_id = State()  # ввод ID для физического удаления


# ── Вход в корзину ────────────────────────────────────────────────────────────


@router.message(F.text == "🗑 Корзина")
async def trash_list(message: Message, state: FSMContext):
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return

        svc = make_task_service(uow)
        tasks, total = await svc.get_deleted_tasks(user, offset=0, limit=PAGE_SIZE)

    is_admin = user.role in (UserRole.admin, UserRole.manager)

    if not tasks:
        await message.answer(
            "🗑 Корзина пуста.",
            reply_markup=trash_keyboard(is_admin),
        )
    else:
        lines = [f"🗑 <b>Корзина</b> (всего: {total})\n"]
        for t in tasks:
            lines.append(f"🆔 {t.id} — <b>{t.title}</b>\n   🕒 Удалено: {to_local(t.deleted_at)}\n")
        await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=trash_keyboard(is_admin))

    await state.set_state(TrashMenu.browsing)


# ── Восстановить ─────────────────────────────────────────────────────────────


@router.message(TrashMenu.browsing, F.text == "♻️ Восстановить задачу")
async def trash_restore_start(message: Message, state: FSMContext):
    await state.set_state(TrashMenu.restore_id)
    await message.answer("Введите ID задачи для восстановления:")


@router.message(TrashMenu.restore_id)
async def trash_restore_confirm(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.set_state(TrashMenu.browsing)
        await message.answer("Отменено.")
        return

    try:
        if message.text is None:
            return
        task_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID (число).")
        return
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            await state.clear()
            return

        uow.set_audit_user(user.id)
        svc = make_task_service(uow)

        try:
            task = await svc.restore_task(task_id, user)
            await message.answer(
                f"♻️ Задача <b>{task.title}</b> восстановлена!",
                parse_mode="HTML",
                reply_markup=trash_keyboard(user.role in (UserRole.admin, UserRole.manager)),
            )
        except Exception as e:
            await message.answer(f"❌ {e}")

    await state.set_state(TrashMenu.browsing)


# ── Удалить навсегда (только admin/manager) ───────────────────────────────────


@router.message(TrashMenu.browsing, F.text == "💣 Удалить навсегда")
async def trash_hard_delete_start(message: Message, state: FSMContext):
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user or user.role not in (UserRole.admin, UserRole.manager):
            await message.answer("❌ Недостаточно прав.")
            return

    await state.set_state(TrashMenu.hard_delete_id)
    await message.answer(
        "⚠️ Введите ID задачи для <b>безвозвратного</b> удаления:",
        parse_mode="HTML",
    )


@router.message(TrashMenu.hard_delete_id)
async def trash_hard_delete_confirm(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.set_state(TrashMenu.browsing)
        await message.answer("Отменено.")
        return

    try:
        if message.text is None:
            return
        task_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID (число).")
        return
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user or user.role not in (UserRole.admin, UserRole.manager):
            await message.answer("❌ Недостаточно прав.")
            await state.clear()
            return

        uow.set_audit_user(user.id)
        svc = make_task_service(uow)

        try:
            await svc.hard_delete_task(task_id, user)
            await message.answer(
                f"💣 Задача #{task_id} удалена безвозвратно.",
                reply_markup=trash_keyboard(is_admin=True),
            )
        except Exception as e:
            await message.answer(f"❌ {e}")

    await state.set_state(TrashMenu.browsing)


# ── Выход из корзины ─────────────────────────────────────────────────────────


@router.message(TrashMenu.browsing, F.text == "🔙 Назад")
async def trash_back(message: Message, state: FSMContext):
    await state.clear()
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)

    keyboard = main_menu_admin() if user and user.role in (UserRole.admin, UserRole.manager) else main_menu_user()
    await message.answer("🏠 Главное меню", reply_markup=keyboard)
