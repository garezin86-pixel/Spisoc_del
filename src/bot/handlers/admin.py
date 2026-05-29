from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from src.bot.utils.user_utils import get_main_menu
from src.services.group_service import GroupService

from src.db import get_session_maker
from src.models.user import UserModel
from src.core.security import hash_password
from src.bot.keyboards.main import (
    main_menu_admin,
    admin_users_keyboard,
    admin_groups_keyboard,
    cancel_keyboard
)
from src.db.unit_of_work import UnitOfWork

router = Router()

# --- FSM ---


class AddUser(StatesGroup):
    username = State()
    password = State()
    role = State()
    telegram_id = State()


class BlockUser(StatesGroup):
    user_id = State()


class DeleteUser(StatesGroup):
    user_id = State()


class CreateGroup(StatesGroup):
    name = State()


class AddUserToGroup(StatesGroup):
    group_id = State()
    user_id = State()


class RemoveUserFromGroup(StatesGroup):
    group_id = State()
    user_id = State()


class DeleteGroup(StatesGroup):
    group_id = State()


class ViewGroupMembers(StatesGroup):
    group_id = State()


# --- Middleware: проверка роли ---


async def check_admin(message: Message) -> UserModel | None:
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user or user.role != "admin":
            await message.answer("❌ Доступ только для администратора.")
            return None
        return user


# --- Меню ---


@router.message(F.text == "👥 Пользователи")
async def admin_users_menu(message: Message):
    user = await check_admin(message)
    if not user:
        return
    await message.answer(
        "👥 Управление пользователями:", reply_markup=admin_users_keyboard()
    )


@router.message(F.text == "👤 Группы")
async def admin_groups_menu(message: Message):
    user = await check_admin(message)
    if not user:
        return
    await message.answer(
        "👤 Управление группами:", reply_markup=admin_groups_keyboard()
    )


@router.message(F.text == "🔙 Назад")
async def go_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_admin())


# --- Список пользователей ---


@router.message(F.text == "📋 Список пользователей")
async def list_users(message: Message):
    user = await check_admin(message)
    if not user:
        return

    async with UnitOfWork(get_session_maker()) as uow:
        users = await uow.users.get_all()

    if not users:
        await message.answer("📭 Пользователи не найдены.")
        return

    text = "👥 <b>Список пользователей:</b>\n\n"
    for u in users:
        status = "✅" if u.is_active else "🚫"
        tg = f"@{u.telegram_id}" if u.telegram_id else "не указан"
        text += f"{status} 🆔{u.id} — <b>{u.username}</b> [{u.role}] TG: {tg}\n"

    await message.answer(text, parse_mode="HTML")


# --- Добавить пользователя ---


@router.message(F.text == "➕ Добавить пользователя")
async def add_user_start(message: Message, state: FSMContext):
    user = await check_admin(message)
    if not user:
        return

    await state.set_state(AddUser.username)
    await message.answer("👤 Введите username:", reply_markup=cancel_keyboard())


@router.message(AddUser.username)
async def add_user_username(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=admin_users_keyboard())
        return

    await state.update_data(username=message.text)
    await state.set_state(AddUser.password)
    await message.answer("🔑 Введите пароль:")


@router.message(AddUser.password)
async def add_user_password(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=admin_users_keyboard())
        return

    await state.update_data(password=message.text)
    await state.set_state(AddUser.role)
    await message.answer(
        "👔 Введите роль (user/admin):",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="user")],
                [KeyboardButton(text="admin")],
                [KeyboardButton(text="❌ Отмена")],
            ],
            resize_keyboard=True,
        ),
    )


@router.message(AddUser.role)
async def add_user_role(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=admin_users_keyboard())
        return

    if message.text not in ["user", "admin"]:
        await message.answer("❌ Введите user или admin.")
        return

    await state.update_data(role=message.text)
    await state.set_state(AddUser.telegram_id)
    await message.answer(
        "📱 Введите Telegram ID пользователя\n" "или нажмите Пропустить:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="⏭ Пропустить")],
                [KeyboardButton(text="❌ Отмена")],
            ],
            resize_keyboard=True,
        ),
    )


@router.message(AddUser.telegram_id)
async def add_user_telegram_id(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=admin_users_keyboard())
        return

    telegram_id = None
    if message.text != "⏭ Пропустить":
        try:
            assert message.text is not None
            telegram_id = int(message.text)
        except ValueError:
            await message.answer("❌ Введите корректный Telegram ID.")
            return

    data = await state.get_data()

    async with UnitOfWork(get_session_maker()) as uow:
        existing = await uow.users.get_by_username(data["username"])
        if existing:
            await state.clear()
            await message.answer(
                "❌ Пользователь с таким username уже существует.",
                reply_markup=admin_users_keyboard(),
            )
            return

        new_user = UserModel(
            username=data["username"],
            password_hash=hash_password(data["password"]),
            role=data["role"],
            telegram_id=telegram_id,
        )
        await uow.users.create(new_user)

    await state.clear()
    await message.answer(
        f"✅ Пользователь <b>{data['username']}</b> создан!",
        parse_mode="HTML",
        reply_markup=admin_users_keyboard(),
    )


# --- Заблокировать пользователя ---


@router.message(F.text == "🚫 Заблокировать пользователя")
async def block_user_start(message: Message, state: FSMContext):
    user = await check_admin(message)
    if not user:
        return

    async with UnitOfWork(get_session_maker()) as uow:
        users = await uow.users.get_all()

    text = "👥 Список пользователей:\n\n"
    for u in users:
        status = "✅" if u.is_active else "🚫"
        text += f"{status} 🆔{u.id} — {u.username}\n"

    await state.set_state(BlockUser.user_id)
    await message.answer(
        text + "\n Введите ID пользователя:", reply_markup=cancel_keyboard()
    )


@router.message(BlockUser.user_id)
async def block_user(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=admin_users_keyboard())
        return

    try:
        assert message.text is not None
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID.")
        return

    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_id(user_id)

        if not user:
            await message.answer("❌ Пользователь не найден.")
            return

        user.is_active = not user.is_active
        await uow.users.update(user)
        status = "разблокирован ✅" if user.is_active else "заблокирован 🚫"

    await state.clear()
    await message.answer(
        f"Пользователь <b>{user.username}</b> {status}",
        parse_mode="HTML",
        reply_markup=admin_users_keyboard(),
    )


# --- Удалить пользователя ---


@router.message(F.text == "🗑 Удалить пользователя")
async def delete_user_start(message: Message, state: FSMContext):
    user = await check_admin(message)
    if not user:
        return

    async with UnitOfWork(get_session_maker()) as uow:
        users = await uow.users.get_all()

    text = "👥 Список пользователей:\n\n"
    for u in users:
        text += f"🆔{u.id} — {u.username}\n"

    await state.set_state(DeleteUser.user_id)
    await message.answer(
        text + "\nВведите ID пользователя:", reply_markup=cancel_keyboard()
    )


@router.message(DeleteUser.user_id)
async def delete_user(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=admin_users_keyboard())
        return

    try:
        assert message.text is not None
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID.")
        return

    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_id(user_id)

        if not user:
            await message.answer("❌ Пользователь не найден.")
            return

        username = user.username
        await uow.users.delete(user)

    await state.clear()
    await message.answer(
        f"🗑 Пользователь <b>{username}</b> удалён.",
        parse_mode="HTML",
        reply_markup=admin_users_keyboard(),
    )


# --- Список групп ---


@router.message(F.text == "📋 Список групп")
async def list_groups(message: Message):
    user = await check_admin(message)
    if not user:
        return

    async with UnitOfWork(get_session_maker()) as uow:
        groups = await uow.groups.get_all()

    if not groups:
        await message.answer("📭 Группы не найдены.")
        return

    text = "👥 <b>Список групп:</b>\n\n"
    for g in groups:
        text += f"🆔{g.id} — <b>{g.name}</b>\n"

    await message.answer(text, parse_mode="HTML")


# --- Создать группу ---


@router.message(F.text == "➕ Создать группу")
async def create_group_start(message: Message, state: FSMContext):
    user = await check_admin(message)
    if not user:
        return

    await state.set_state(CreateGroup.name)
    await message.answer("👥 Введите название группы:", reply_markup=cancel_keyboard())


@router.message(CreateGroup.name)
async def create_group(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=admin_groups_keyboard())
        return

    async with UnitOfWork(get_session_maker()) as uow:
        from src.models.group import GroupModel

        group = GroupModel(name=message.text)

        await uow.groups.create(group)

    await state.clear()
    await message.answer(
        f"✅ Группа <b>{message.text}</b> создана!",
        parse_mode="HTML",
        reply_markup=admin_groups_keyboard(),
    )


# --- Добавить пользователя в группу ---


@router.message(F.text == "➕ Добавить в группу")
async def add_to_group_start(message: Message, state: FSMContext):

    async with UnitOfWork(get_session_maker()) as uow:
        groups = await uow.groups.get_all()
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
    if not user or user.role not in ("admin", "manager"):
        await message.answer("❌ У вас нет доступа.")
        return

    text = "👥 Список групп:\n\n"
    for g in groups:
        text += f"🆔{g.id} — {g.name}\n"

    await state.set_state(AddUserToGroup.group_id)
    await message.answer(text + "\nВведите ID группы:", reply_markup=cancel_keyboard())


@router.message(AddUserToGroup.group_id)
async def add_to_group_select_group(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        async with UnitOfWork(get_session_maker()) as uow:
            assert message.from_user is not None
            user = await uow.users.get_by_telegram_id(message.from_user.id)

        await state.clear()
        kb = (
            admin_groups_keyboard()
            if user and user.role == "admin"
            else get_main_menu(user)
        )
        await message.answer("❌ Отменено.", reply_markup=kb)
        return

    try:
        assert message.text is not None
        group_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID.")
        return

    await state.update_data(group_id=group_id)

    async with UnitOfWork(get_session_maker()) as uow:
        users = await uow.users.get_all()

    text = "👥 Список пользователей:\n\n"
    for u in users:
        text += f"🆔{u.id} — {u.username}\n"

    await state.set_state(AddUserToGroup.user_id)
    await message.answer(text + "\nВведите ID пользователя:")


@router.message(AddUserToGroup.user_id)
async def add_to_group_select_user(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=admin_groups_keyboard())
        return

    try:
        assert message.text is not None
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID.")
        return

    data = await state.get_data()

    async with UnitOfWork(get_session_maker()) as uow:
        service = GroupService(group_repo=uow.groups, user_repo=uow.users)
        await service.add_user_to_group(data["group_id"], user_id)
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        service = GroupService(group_repo=uow.groups, user_repo=uow.users)
        await service.add_user_to_group(data["group_id"], user_id)

    await state.clear()
    kb = (
        admin_groups_keyboard()
        if user and user.role == "admin"
        else get_main_menu(user)
    )
    await message.answer("✅ Пользователь добавлен в группу.", reply_markup=kb)


# --- Удалить из группы ---


@router.message(F.text == "➖ Удалить из группы")
async def remove_from_group_start(message: Message, state: FSMContext):
    async with UnitOfWork(get_session_maker()) as uow:
        groups = await uow.groups.get_all()
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
    if not user or user.role not in ("admin", "manager"):
        await message.answer("❌ У вас нет доступа.")
        return

    text = "👥 Список групп:\n\n"
    for g in groups:
        text += f"🆔{g.id} — {g.name}\n"

    await state.set_state(RemoveUserFromGroup.group_id)
    await message.answer(text + "\nВведите ID группы:", reply_markup=cancel_keyboard())


@router.message(RemoveUserFromGroup.group_id)
async def remove_from_group_select_group(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        async with UnitOfWork(get_session_maker()) as uow:
            assert message.from_user is not None
            user = await uow.users.get_by_telegram_id(message.from_user.id)

        await state.clear()
        kb = (
            admin_groups_keyboard()
            if user and user.role == "admin"
            else get_main_menu(user)
        )
        await message.answer("❌ Отменено.", reply_markup=kb)
        return

    try:
        assert message.text is not None
        group_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID.")
        return

    await state.update_data(group_id=group_id)

    async with UnitOfWork(get_session_maker()) as uow:
        users = await uow.groups.get_group_users(group_id)

    if not users:
        await state.clear()
        await message.answer(
            "📭 В группе нет пользователей.", reply_markup=admin_groups_keyboard()
        )
        return

    text = "👥 Пользователи в группе:\n\n"
    for u in users:
        text += f"🆔{u.id} — {u.username}\n"

    await state.set_state(RemoveUserFromGroup.user_id)
    await message.answer(text + "\nВведите ID пользователя:")


@router.message(RemoveUserFromGroup.user_id)
async def remove_from_group_select_user(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=admin_groups_keyboard())
        return

    try:
        assert message.text is not None
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID.")
        return

    data = await state.get_data()

    async with UnitOfWork(get_session_maker()) as uow:
        service = GroupService(group_repo=uow.groups, user_repo=uow.users)
        await service.delete_group_user(data["group_id"], user_id)
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        service = GroupService(group_repo=uow.groups, user_repo=uow.users)
        await service.add_user_to_group(data["group_id"], user_id)

    await state.clear()
    kb = (
        admin_groups_keyboard()
        if user and user.role == "admin"
        else get_main_menu(user)
    )
    await message.answer("✅ Пользователь удалён из группы.", reply_markup=kb)


# --- Удалить группу ---


@router.message(F.text == "🗑 Удалить группу")
async def delete_group_start(message: Message, state: FSMContext):
    user = await check_admin(message)
    if not user:
        return

    async with UnitOfWork(get_session_maker()) as uow:
        groups = await uow.groups.get_all()

    text = "👥 Список групп:\n\n"
    for g in groups:
        text += f"🆔{g.id} — {g.name}\n"

    await state.set_state(DeleteGroup.group_id)
    await message.answer(text + "\nВведите ID группы:", reply_markup=cancel_keyboard())


@router.message(DeleteGroup.group_id)
async def delete_group(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=admin_groups_keyboard())
        return

    try:
        assert message.text is not None
        group_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID.")
        return

    async with UnitOfWork(get_session_maker()) as uow:
        group = await uow.groups.get_by_id(group_id)

        if not group:
            await message.answer("❌ Группа не найдена.")
            return

        name = group.name
        await uow.session.delete(group)
        await uow.session.commit()

    await state.clear()
    await message.answer(
        f"🗑 Группа <b>{name}</b> удалена.",
        parse_mode="HTML",
        reply_markup=admin_groups_keyboard(),
    )


# ============ ПРОСМОТР ГРУППЫ ПОЛЬЗОВАТЕЛЯ ============


async def check_user(message: Message) -> UserModel | None:
    """Проверка аутентификации обычного пользователя"""
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return None
        return user


@router.message(F.text == "👥 Моя группа")
async def view_my_group(message: Message):
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)

        if not user:
            await message.answer("❌ У вас нет доступа.")
            return

        groups = await uow.groups.get_user_groups(user.id)

        if not groups:
            await message.answer("📭 Вы не входите ни в какую группу.")
            await message.answer("Вернулись в меню.", reply_markup=get_main_menu(user))
            return

        texts = []

        for group in groups:
            members = await uow.groups.get_group_users(group.id)
            members_count = len(members) if members else 0
            text = f"👥 <b>{group.name}</b>\n"
            text += f"🆔 ID: {group.id}\n"
            text += f"👤 Участников: {members_count}\n\n"
            text += "👥 Участники:\n"

            if members:
                for member in members:
                    text += f"• {member.username}\n"
            else:
                text += "Нет участников"

            texts.append(text)  # ← вот это строка была пропущена

    await message.answer("\n\n".join(texts), parse_mode="HTML")


# ============ ПРОСМОТР УЧАСТНИКОВ ГРУППЫ (ДЛЯ АДМИНА) ============


@router.message(ViewGroupMembers.group_id, F.text == "❌ Отмена")
async def cancel_view_group_members(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=admin_groups_keyboard())


@router.message(F.text == "📋 Список участников групп")
async def admin_view_group_members_start(message: Message, state: FSMContext):
    user = await check_admin(message)
    if not user:
        return

    async with UnitOfWork(get_session_maker()) as uow:
        groups = await uow.groups.get_all()

        if not groups:
            await message.answer("📭 Нет групп.", reply_markup=admin_groups_keyboard())
            return

        text = "👥 <b>Список групп:</b>\n\n"
        for g in groups:
            members_count = len(g.users) if g.users else 0
            text += f"🆔 {g.id} — <b>{g.name}</b> (👤 {members_count})\n"

        await message.answer(text, parse_mode="HTML")
        await state.set_state(ViewGroupMembers.group_id)
        await message.answer(
            "Введите ID группы для просмотра участников:",
            reply_markup=cancel_keyboard(),
        )


@router.message(ViewGroupMembers.group_id)
async def admin_show_group_members(message: Message, state: FSMContext):
    try:
        assert message.text is not None
        group_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID группы (число).")
        return  # не чистим стейт — даём попробовать снова

    async with UnitOfWork(get_session_maker()) as uow:
        group = await uow.groups.get_by_id_users_in_group(group_id)

        if not group:
            await message.answer(
                "❌ Группа не найдена. Введите другой ID или нажмите отмену."
            )
            return  # не чистим стейт — даём попробовать снова

        users = group.users
        text = f"👥 <b>Группа: {group.name}</b>\n"
        text += f"🆔 ID: {group.id}\n"
        text += f"👤 Участников: {len(users)}\n\n"

        if users:
            text += "<b>Участники:</b>\n"
            for member in users:
                status = "✅" if member.is_active else "❌"
                role = f" [{member.role}]" if member.role != "user" else ""
                text += f"{status} • {member.username}{role}\n"
        else:
            text += "В группе нет участников."

    await message.answer(text, parse_mode="HTML")
    # После показа предлагаем посмотреть другую группу или выйти
    await message.answer(
        "Введите ID другой группы или нажмите отмену:", reply_markup=cancel_keyboard()
    )
    # стейт НЕ чистим — остаёмся в режиме просмотра
