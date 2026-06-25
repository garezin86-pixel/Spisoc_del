"""
Хендлеры проектов в Telegram-боте.

Меню проектов доступно всем пользователям — просмотр своих проектов.
Создание/удаление/управление участниками — только admin и manager.

Сценарии:
  📁 Мои проекты      — список проектов пользователя
  🔍 Проект по ID     — детали + задачи проекта
  ➕ Создать проект   — FSM (только admin/manager)
  ➕ Добавить участника — FSM по project_id + username
  ➖ Удалить участника  — FSM по project_id + username
  🗑 Удалить проект   — FSM (только admin/manager)
  🔙 Назад           — в главное меню
"""

from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.models.user import UserRole
from src.repositories.project_repository import ProjectRepository
from src.repositories.users_repository import UserRepository
from src.repositories.groups_repository import GroupRepository
from src.repositories.task_repository import TaskRepository
from src.models.task import SpisokModel
from src.services.task_service import TaskService
from src.schemas.schemas_project import ProjectCreate
from src.services.project_service import ProjectService
from src.bot.keyboards.main import (
    projects_menu_keyboard,
    projects_admin_keyboard,
    cancel_keyboard,
    get_main_menu_keyboard,
)

router = Router()

PAGE_SIZE = 8


# ── фабрика сервиса ───────────────────────────────────────────────────────────


def make_project_service(uow: UnitOfWork) -> ProjectService:
    return ProjectService(
        project_repo=ProjectRepository(uow.session),
        user_repo=UserRepository(uow.session),
        group_repo=GroupRepository(uow.session),
    )


# ── FSM-состояния ─────────────────────────────────────────────────────────────


class ProjectMenu(StatesGroup):
    browsing = State()  # главное меню проектов
    view_id = State()  # ввод ID для просмотра
    create_name = State()  # ввод названия нового проекта
    create_desc = State()  # ввод описания (опционально)
    add_member_project = State()  # ввод ID проекта для добавления участника
    add_member_username = State()  # ввод @username участника
    del_member_project = State()  # ввод ID проекта для удаления участника
    del_member_username = State()  # ввод @username участника
    delete_id = State()  # ввод ID проекта для удаления
    assign_group_task_id = State()  # ввод ID задачи для назначения на группу
    assign_group_id = State()  # ввод ID группы


# ── хелперы ───────────────────────────────────────────────────────────────────


def _is_manager(user) -> bool:
    return user.role in (UserRole.admin, UserRole.manager)


def _fmt_project_short(p, idx: int) -> str:
    done = sum(1 for t in p.tasks if t.status and t.status.value == "done")
    total = len(p.tasks)
    pct = round(done / total * 100) if total else 0
    return (
        f"{idx}. <b>{p.name}</b> 🆔{p.id}\n"
        f"   📋 Задач: {total}  ✅ {done} ({pct}%)\n"
        f"   👥 Участников: {len(p.members)}"
    )


_TASK_STATUS_EMOJI = {
    "done": "✅",
    "in_progress": "⚙️",
    "review": "👁",
    "todo": "📋",
    "backlog": "📥",
}


def _fmt_project_full(p) -> str:
    done = sum(1 for t in p.tasks if t.status and t.status.value == "done")
    total = len(p.tasks)
    pct = round(done / total * 100) if total else 0

    members_str = ", ".join(f"@{m.username}" for m in p.members) or "нет участников"
    owner_str = f"@{p.owner.username}" if p.owner else "?"
    group_str = p.group.name if p.group else "не привязана"

    # последние 10 задач
    tasks_lines = []
    for t in sorted(p.tasks, key=lambda x: x.created_at or 0, reverse=True)[:10]:
        st = _TASK_STATUS_EMOJI.get(t.status.value if t.status else "todo", "⏳")
        tasks_lines.append(f"  {st} {t.title} (#{t.id})")
    tasks_str = "\n".join(tasks_lines) if tasks_lines else "  нет задач"

    return (
        f"📁 <b>{p.name}</b> 🆔{p.id}\n\n"
        f"📝 {p.description or 'Нет описания'}\n\n"
        f"👑 Владелец: {owner_str}\n"
        f"👥 Группа: {group_str}\n"
        f"👤 Участники: {members_str}\n\n"
        f"📊 Прогресс: {done}/{total} ({pct}%)\n\n"
        f"<b>Задачи:</b>\n{tasks_str}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Вход в меню проектов
# ══════════════════════════════════════════════════════════════════════════════


@router.message(F.text == "📁 Проекты")
async def projects_enter(message: Message, state: FSMContext):
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return

    kb = projects_admin_keyboard() if _is_manager(user) else projects_menu_keyboard()
    await message.answer(
        "📁 <b>Проекты</b>\nВыберите действие:", parse_mode="HTML", reply_markup=kb
    )
    await state.set_state(ProjectMenu.browsing)


# ══════════════════════════════════════════════════════════════════════════════
# Список проектов
# ══════════════════════════════════════════════════════════════════════════════


@router.message(ProjectMenu.browsing, F.text == "📋 Мои проекты")
async def projects_list(message: Message, state: FSMContext):
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return
        projects, total = await make_project_service(uow).get_projects(
            user, offset=0, limit=PAGE_SIZE
        )

    if not projects:
        await message.answer("📭 У вас нет проектов.")
        return

    lines = [f"📁 <b>Проекты</b> (всего: {total})\n"]
    for i, p in enumerate(projects, 1):
        lines.append(_fmt_project_short(p, i))

    await message.answer("\n\n".join(lines), parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════════════════
# Просмотр проекта по ID
# ══════════════════════════════════════════════════════════════════════════════


@router.message(ProjectMenu.browsing, F.text == "🔍 Проект по ID")
async def projects_view_start(message: Message, state: FSMContext):
    await state.set_state(ProjectMenu.view_id)
    await message.answer("Введите ID проекта:", reply_markup=cancel_keyboard())


@router.message(ProjectMenu.view_id)
async def projects_view(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await _back_to_projects(message, state)
        return

    try:
        project_id = int(message.text or "")
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
        try:
            project = await make_project_service(uow).get_project(project_id, user)
            await message.answer(_fmt_project_full(project), parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ {e}")

    await _back_to_projects(message, state)


# ══════════════════════════════════════════════════════════════════════════════
# Создать проект (admin/manager)
# ══════════════════════════════════════════════════════════════════════════════


@router.message(ProjectMenu.browsing, F.text == "➕ Создать проект")
async def project_create_start(message: Message, state: FSMContext):
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user or not _is_manager(user):
            await message.answer("❌ Требуется роль admin или manager.")
            return

    await state.set_state(ProjectMenu.create_name)
    await message.answer("Введите название проекта:", reply_markup=cancel_keyboard())


@router.message(ProjectMenu.create_name)
async def project_create_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await _back_to_projects(message, state)
        return

    await state.update_data(name=message.text)
    await state.set_state(ProjectMenu.create_desc)
    await message.answer(
        "Введите описание проекта (или нажмите «⏭ Пропустить»):",
        reply_markup=_skip_cancel_kb(),
    )


@router.message(ProjectMenu.create_desc)
async def project_create_desc(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await _back_to_projects(message, state)
        return

    description = None if message.text == "⏭ Пропустить" else message.text
    data = await state.get_data()

    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            await state.clear()
            return
        try:
            project = await make_project_service(uow).create_project(
                ProjectCreate(
                    name=data["name"], description=description, group_id=None
                ),
                user,
            )
            await message.answer(
                f"✅ Проект <b>{project.name}</b> создан! 🆔{project.id}",
                parse_mode="HTML",
            )
        except Exception as e:
            await message.answer(f"❌ {e}")

    await _back_to_projects(message, state)


# ══════════════════════════════════════════════════════════════════════════════
# Добавить участника
# ══════════════════════════════════════════════════════════════════════════════


@router.message(ProjectMenu.browsing, F.text == "➕ Добавить участника")
async def project_add_member_start(message: Message, state: FSMContext):
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user or not _is_manager(user):
            await message.answer("❌ Требуется роль admin или manager.")
            return

    await state.set_state(ProjectMenu.add_member_project)
    await message.answer("Введите ID проекта:", reply_markup=cancel_keyboard())


@router.message(ProjectMenu.add_member_project)
async def project_add_member_project_id(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await _back_to_projects(message, state)
        return
    try:
        await state.update_data(project_id=int(message.text or ""))
    except ValueError:
        await message.answer("❌ Введите корректный ID (число).")
        return
    await state.set_state(ProjectMenu.add_member_username)
    await message.answer(
        "Введите @username пользователя:", reply_markup=cancel_keyboard()
    )


@router.message(ProjectMenu.add_member_username)
async def project_add_member_do(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await _back_to_projects(message, state)
        return

    username = (message.text or "").lstrip("@").strip()
    data = await state.get_data()

    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            await state.clear()
            return
        target = await uow.users.get_by_username(username)
        if not target:
            await message.answer(f"❌ Пользователь @{username} не найден.")
            await _back_to_projects(message, state)
            return
        try:
            result = await make_project_service(uow).add_member(
                data["project_id"], target.id, user
            )
            await message.answer(f"✅ {result['message']}")
        except Exception as e:
            await message.answer(f"❌ {e}")

    await _back_to_projects(message, state)


# ══════════════════════════════════════════════════════════════════════════════
# Удалить участника
# ══════════════════════════════════════════════════════════════════════════════


@router.message(ProjectMenu.browsing, F.text == "➖ Удалить участника")
async def project_del_member_start(message: Message, state: FSMContext):
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user or not _is_manager(user):
            await message.answer("❌ Требуется роль admin или manager.")
            return

    await state.set_state(ProjectMenu.del_member_project)
    await message.answer("Введите ID проекта:", reply_markup=cancel_keyboard())


@router.message(ProjectMenu.del_member_project)
async def project_del_member_project_id(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await _back_to_projects(message, state)
        return
    try:
        await state.update_data(project_id=int(message.text or ""))
    except ValueError:
        await message.answer("❌ Введите корректный ID (число).")
        return
    await state.set_state(ProjectMenu.del_member_username)
    await message.answer(
        "Введите @username пользователя:", reply_markup=cancel_keyboard()
    )


@router.message(ProjectMenu.del_member_username)
async def project_del_member_do(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await _back_to_projects(message, state)
        return

    username = (message.text or "").lstrip("@").strip()
    data = await state.get_data()

    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            await state.clear()
            return
        target = await uow.users.get_by_username(username)
        if not target:
            await message.answer(f"❌ Пользователь @{username} не найден.")
            await _back_to_projects(message, state)
            return
        try:
            result = await make_project_service(uow).remove_member(
                data["project_id"], target.id, user
            )
            await message.answer(f"✅ {result['message']}")
        except Exception as e:
            await message.answer(f"❌ {e}")

    await _back_to_projects(message, state)


# ══════════════════════════════════════════════════════════════════════════════
# Удалить проект (только owner/admin)
# ══════════════════════════════════════════════════════════════════════════════


@router.message(ProjectMenu.browsing, F.text == "🗑 Удалить проект")
async def project_delete_start(message: Message, state: FSMContext):
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user or not _is_manager(user):
            await message.answer("❌ Требуется роль admin или manager.")
            return

    await state.set_state(ProjectMenu.delete_id)
    await message.answer(
        "⚠️ Введите ID проекта для удаления.\n"
        "<b>Все задачи проекта будут удалены!</b>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.message(ProjectMenu.delete_id)
async def project_delete_do(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await _back_to_projects(message, state)
        return

    try:
        project_id = int(message.text or "")
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
        try:
            await make_project_service(uow).delete_project(project_id, user)
            await message.answer(f"🗑 Проект #{project_id} удалён.")
        except Exception as e:
            await message.answer(f"❌ {e}")

    await _back_to_projects(message, state)


# ══════════════════════════════════════════════════════════════════════════════
# Назад
# ══════════════════════════════════════════════════════════════════════════════


@router.message(ProjectMenu.browsing, F.text == "🔄 Назначить задачу на группу")
async def assign_task_group_start(message: Message, state: FSMContext):
    """Шаг 1 — спрашиваем ID задачи."""
    await state.set_state(ProjectMenu.assign_group_task_id)
    await message.answer(
        "🔄 <b>Назначение задачи на группу</b>\n\n"
        "Введите ID задачи которую хотите назначить на группу:\n"
        "<i>(ID задачи указан в сообщении задачи как 🆔 ID: N)</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.message(ProjectMenu.assign_group_task_id, F.text == "❌ Отмена")
async def assign_task_group_cancel_1(message: Message, state: FSMContext):
    await state.set_state(ProjectMenu.browsing)

    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
    kb = (
        projects_admin_keyboard()
        if user and _is_manager(user)
        else projects_menu_keyboard()
    )
    await message.answer("❌ Отменено.", reply_markup=kb)


@router.message(ProjectMenu.assign_group_task_id)
async def assign_task_group_get_task_id(message: Message, state: FSMContext):
    """Шаг 2 — получаем ID задачи, спрашиваем ID группы."""
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❌ Введите числовой ID задачи.")
        return

    task_id = int(text)
    async with UnitOfWork(get_session_maker()) as uow:
        task = await uow.session.get(SpisokModel, task_id)
        if not task or task.deleted_at is not None:
            await message.answer(f"❌ Задача #{task_id} не найдена.")
            return

        # Показываем список групп
        from sqlalchemy import select as sa_select
        from src.models.group import GroupModel

        result = await uow.session.execute(sa_select(GroupModel).limit(20))
        groups = list(result.scalars().all())

    if not groups:
        await message.answer("❌ В системе нет групп.")
        return

    await state.update_data(assign_task_id=task_id, task_title=task.title)
    await state.set_state(ProjectMenu.assign_group_id)

    lines = [f"📌 Задача: <b>{task.title}</b>\n", "👥 <b>Доступные группы:</b>"]
    for g in groups:
        lines.append(f"  • ID <code>{g.id}</code> — {g.name}")
    lines.append("\nВведите ID группы:")

    await message.answer(
        "\n".join(lines), parse_mode="HTML", reply_markup=cancel_keyboard()
    )


@router.message(ProjectMenu.assign_group_id, F.text == "❌ Отмена")
async def assign_task_group_cancel_2(message: Message, state: FSMContext):
    await state.set_state(ProjectMenu.browsing)
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
    kb = (
        projects_admin_keyboard()
        if user and _is_manager(user)
        else projects_menu_keyboard()
    )
    await message.answer("❌ Отменено.", reply_markup=kb)


@router.message(ProjectMenu.assign_group_id)
async def assign_task_group_finish(message: Message, state: FSMContext):
    """Шаг 3 — назначаем задачу на группу."""
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❌ Введите числовой ID группы.")
        return

    group_id = int(text)
    data = await state.get_data()
    task_id: int = data["assign_task_id"]
    task_title: str = data["task_title"]

    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return

        svc = TaskService(
            task_repo=TaskRepository(uow.session),
            user_repo=UserRepository(uow.session),
            group_repo=GroupRepository(uow.session),
            session=uow.session,
        )

        try:
            task = await svc.reassign_task(
                task_id=task_id,
                current_user=user,
                user_id=None,
                group_id=group_id,
            )
            await uow.commit()
            group_name = task.group.name if task.group else f"#{group_id}"
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
            await state.set_state(ProjectMenu.browsing)
            return

    await state.set_state(ProjectMenu.browsing)
    kb = projects_admin_keyboard() if _is_manager(user) else projects_menu_keyboard()
    await message.answer(
        f"✅ <b>Задача назначена на группу!</b>\n\n"
        f"📌 {task_title}\n"
        f"👥 Группа: {group_name}",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.message(ProjectMenu.browsing, F.text == "🔙 Назад")
async def projects_back(message: Message, state: FSMContext):
    await state.clear()
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
    kb = get_main_menu_keyboard(user)
    await message.answer("🏠 Главное меню", reply_markup=kb)


# ── внутренние хелперы ────────────────────────────────────────────────────────


async def _back_to_projects(message: Message, state: FSMContext):
    """Возвращаемся в меню проектов без выхода из состояния browsing."""
    assert message.from_user is not None
    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
    kb = (
        projects_admin_keyboard()
        if (user and _is_manager(user))
        else projects_menu_keyboard()
    )
    await message.answer("📁 Проекты:", reply_markup=kb)
    await state.set_state(ProjectMenu.browsing)


def _skip_cancel_kb():
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Пропустить")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )
