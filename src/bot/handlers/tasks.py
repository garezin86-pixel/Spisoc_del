from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram.utils.keyboard import ReplyKeyboardBuilder as _RKB

from src.bot.utils.user_utils import get_main_menu, get_task_edit_keyboard
from src.db import get_session_maker
from src.models.task import SpisokModel
from src.schemas.task import FilterUserGroup, TaskFilter, SpisokUpdate
from src.schemas.comment import CommentCreate
from src.repositories.users_repository import UserRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.groups_repository import GroupRepository
from src.repositories.other_repositories import CommentRepository
from src.models.task import TaskPriority, TaskStatus
from src.services.notifications import notify_task_assigned, notify_task_updated
from src.services.task_service import TaskService
from src.services.comments_service import CommentService
from src.bot.keyboards.main import (
    assign_to_keyboard,
    skip_or_cancel,
    cancel_keyboard,
    task_edit_manager_keyboard,
    task_filters_keyboard,
    task_edit_keyboard,
    comments_action_keyboard,
)

from src.utils.datetime_utils import to_local
from src.db.unit_of_work import UnitOfWork

LOCAL_TZ = ZoneInfo("Europe/Kiev")

router = Router()

STATUS_EMOJI = {
    "done": "✅",
    "in_progress": "⚙️",
    "review": "👁",
    "todo": "📋",
    "backlog": "📥",
}

STATUS_LABEL = {
    "done": "✅ Выполнена",
    "in_progress": "⚙️ В работе",
    "review": "👁 На проверке",
    "todo": "📋 Новая",
    "backlog": "📥 В очереди",
}


def _status_emoji(task) -> str:
    key = task.status.value if task.status else "todo"
    return STATUS_EMOJI.get(key, "⏳")


def _status_label(task) -> str:
    key = task.status.value if task.status else "todo"
    return STATUS_LABEL.get(key, "⏳ Неизвестно")


# ── хелперы: создать сервис из uow ──────────────────────────────────────────
def make_task_service(uow: UnitOfWork) -> TaskService:
    return TaskService(
        task_repo=TaskRepository(uow.session),
        user_repo=UserRepository(uow.session),
        group_repo=GroupRepository(uow.session),
        session=uow.session,
    )


def make_comment_service(uow: UnitOfWork) -> CommentService:
    return CommentService(
        task_repo=TaskRepository(uow.session),
        comment_repo=CommentRepository(uow.session),
        session=uow.session,
        group_repo=GroupRepository(uow.session),
    )


class CreateTask(StatesGroup):
    title = State()
    description = State()
    assign_to = State()
    select_user = State()
    select_group = State()
    priority = State()
    deadline = State()


class TaskFilters(StatesGroup):
    waiting_for_task_id = State()


class EditTask(StatesGroup):
    task_id = State()
    edit_type = State()
    new_value = State()


class AddComment(StatesGroup):
    task_id = State()
    comment_text = State()
    action_choice = State()


class TaskMenu(StatesGroup):
    view = State()


class ReassignTask(StatesGroup):
    assign_to = State()
    select_user = State()
    select_group = State()


@router.message(F.text == "📋 Мои задачи")
async def my_tasks(message: Message):
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return
        tasks = await uow.tasks.get_user_tasks(user.id)
        if not tasks:
            await message.answer("📭 У вас нет задач.")
            return
        for task in tasks:
            status = _status_emoji(task)
            deadline = to_local(task.deadline)
            await message.answer(
                f"{status} <b>{task.title}</b>\n"
                f"🎯 {'🔴' if hasattr(task, 'priority')
                      and task.priority and task.priority.value == 'critical'
                      else '🟠' if hasattr(task, 'priority')
                      and task.priority and task.priority.value == 'high'
                      else '🔵' if hasattr(task, 'priority')
                      and task.priority and task.priority.value == 'medium'
                      else '⚪'} Приоритет\n"
                f"📅 Дедлайн: {deadline}\n"
                f"🆔 ID: {task.id}",
                parse_mode="HTML",
            )


@router.message(F.text == "✅ Выполненные")
async def done_tasks(message: Message):
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return
        tasks = await uow.tasks.get_user_tasks_by_status(user.id, done=True)
        if not tasks:
            await message.answer("📭 Нет выполненных задач.")
            return
        for task in tasks:
            await message.answer(
                f"✅ <b>{task.title}</b>\n📅 {to_local(task.deadline)}\n🆔 ID: {task.id}",
                parse_mode="HTML",
            )


@router.message(F.text == "⏳ Невыполненные")
async def pending_tasks(message: Message):
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return
        tasks = await uow.tasks.get_user_tasks_by_status(user.id, done=False)
        if not tasks:
            await message.answer("📭 Нет невыполненных задач.")
            return
        for task in tasks:
            await message.answer(
                f"⏳ <b>{task.title}</b>\n📅 {to_local(task.deadline)}\n🆔 ID: {task.id}",
                parse_mode="HTML",
            )


@router.message(F.text == "📝 Создать задачу")
async def create_task_start(message: Message, state: FSMContext):
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return
    await state.set_state(CreateTask.title)
    await message.answer("📝 Введите название задачи:", reply_markup=cancel_keyboard())


@router.message(CreateTask.title)
async def create_task_title(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        async with UnitOfWork(get_session_maker()) as uow:
            assert message.from_user is not None
            user = await uow.users.get_by_telegram_id(message.from_user.id)
            if not user:
                await message.answer("❌ Пользователь не найден.")
                return
            # keyboard = main_menu_admin() if user.role == "admin" else main_menu_user()
            keyboard = get_main_menu(user)
        await message.answer("❌ Отменено.", reply_markup=keyboard)
        return
    await state.update_data(title=message.text)
    await state.set_state(CreateTask.description)
    await message.answer("📄 Введите описание задачи:", reply_markup=skip_or_cancel())


@router.message(CreateTask.description)
async def create_task_description(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.")
        return
    description = None if message.text == "⏭ Пропустить" else message.text
    await state.update_data(description=description)
    await state.set_state(CreateTask.assign_to)
    await message.answer("👤 Кому назначить задачу?", reply_markup=assign_to_keyboard())


@router.message(CreateTask.assign_to)
async def create_task_assign(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.")
        return
    if message.text == "👤 Пользователю":
        async with UnitOfWork(get_session_maker()) as uow:
            users = await uow.users.get_all()
        if not users:
            await message.answer("❌ Пользователи не найдены.")
            return
        text = "👤 Выберите пользователя — введите его ID:\n\n"
        for u in users:
            text += f"🆔 {u.id} — {u.username}\n"
        await state.set_state(CreateTask.select_user)
        await message.answer(text, reply_markup=cancel_keyboard())
    elif message.text == "👥 Группе":
        async with UnitOfWork(get_session_maker()) as uow:
            groups = await uow.groups.get_all()
        if not groups:
            await message.answer("❌ Группы не найдены.")
            return
        text = "👥 Выберите группу — введите её ID:\n\n"
        for g in groups:
            text += f"🆔 {g.id} — {g.name}\n"
        await state.set_state(CreateTask.select_group)
        await message.answer(text, reply_markup=cancel_keyboard())
    elif message.text == "🚫 Без назначения":
        await state.update_data(user_id=None, group_id=None)
        await state.set_state(CreateTask.priority)
        await message.answer("🎯 Выберите приоритет:", reply_markup=priority_keyboard())


@router.message(CreateTask.select_user)
async def create_task_select_user(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.")
        return
    try:
        assert message.text is not None
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID пользователя.")
        return
    await state.update_data(user_id=user_id, group_id=None)
    await state.set_state(CreateTask.priority)
    await message.answer("🎯 Выберите приоритет:", reply_markup=priority_keyboard())


@router.message(CreateTask.select_group)
async def create_task_select_group(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.")
        return
    try:
        assert message.text is not None
        group_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID группы.")
        return
    await state.update_data(group_id=group_id, user_id=None)
    await state.set_state(CreateTask.priority)
    await message.answer("🎯 Выберите приоритет:", reply_markup=priority_keyboard())


def priority_keyboard():
    """Клавиатура выбора приоритета задачи."""
    kb = _RKB()
    kb.button(text="🔴 Критический")
    kb.button(text="🟠 Высокий")
    kb.button(text="🔵 Средний")
    kb.button(text="⚫ Низкий")
    kb.button(text="❌ Отмена")
    kb.adjust(2, 2, 1)
    return kb.as_markup(resize_keyboard=True)


@router.message(CreateTask.priority)
async def create_task_priority(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.")
        return
    priority_map = {
        "🔴 Критический": "critical",
        "🟠 Высокий": "high",
        "🔵 Средний": "medium",
        "⚫ Низкий": "low",
    }
    text = message.text or ""
    priority = priority_map.get(text, "medium")
    await state.update_data(priority=priority)
    await state.set_state(CreateTask.deadline)
    skip_kb = _RKB()
    skip_kb.button(text="⏭ Пропустить")
    skip_kb.button(text="❌ Отмена")
    skip_kb.adjust(2)
    await message.answer(
        "📅 Введите дедлайн (ДД.ММ.ГГГГ ЧЧ:ММ) или пропустите:",
        reply_markup=skip_kb.as_markup(resize_keyboard=True),
    )


@router.message(CreateTask.deadline)
async def create_task_deadline(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отменено.")
        return
    deadline = None
    if message.text != "⏭ Пропустить":
        try:
            assert message.text is not None
            deadline = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        except ValueError:
            await message.answer(
                "❌ Неверный формат даты.\nВведите в формате ДД.ММ.ГГГГ ЧЧ:ММ\nНапример: 25.12.2025 18:00"
            )
            return
    data = await state.get_data()
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return

        uow.set_audit_user(user.id)

        priority_value = data.get("priority", "medium")
        task = SpisokModel(
            title=data["title"],
            description=data.get("description"),
            user_id=data.get("user_id"),
            group_id=data.get("group_id"),
            deadline=deadline,
            author_id=user.id,
            priority=TaskPriority(priority_value),
        )
        created_task = await uow.tasks.create(task)
        await uow.session.flush()
        await notify_task_assigned(created_task.id)
    await state.clear()
    await message.answer(
        f"✅ Задача <b>{created_task.title}</b> создана!",
        parse_mode="HTML",
        # reply_markup=main_menu_admin() if user.role == "admin" else main_menu_user(),
        reply_markup=get_main_menu(user),
    )


# ============ ФИЛЬТРАЦИЯ ЗАДАЧ ============


@router.message(F.text == "🔍 Фильтры")
async def task_filters_menu(message: Message):
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return
    await message.answer("🔍 Выберите фильтр:", reply_markup=task_filters_keyboard())


@router.message(F.text == "🔙 Назад")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return
        # keyboard = main_menu_admin() if user.role == "admin" else main_menu_user()
        keyboard = get_main_menu(user)
    await message.answer("🔙 Вернулись в меню.", reply_markup=keyboard)


async def _filter_and_send(
    message: Message, filter_type: TaskFilter, empty_text: str, header: str
):
    """Общий хелпер для фильтров задач."""
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return
        try:
            tasks = await make_task_service(uow).filter_tasks(
                current_user=user,
                filter_user_group=FilterUserGroup.user,
                group_id=None,
                filter_type=filter_type,
                is_done=None,
                limit=100,
                offset=0,
            )
            if not tasks:
                await message.answer(empty_text)
                return
            await message.answer(f"<b>{header}</b>\n", parse_mode="HTML")
            for task in tasks:
                status = _status_emoji(task)
                await message.answer(
                    f"{status} <b>{task.title}</b>\n📅 {to_local(task.deadline)}\n🆔 ID: {task.id}",
                    parse_mode="HTML",
                )
        except Exception as e:
            await message.answer(f"❌ Ошибка при получении задач: {str(e)}")


@router.message(F.text == "📅 На сегодня")
async def filter_today(message: Message):
    await _filter_and_send(
        message, TaskFilter.today, "📭 Нет задач на сегодня.", "📅 Задачи на сегодня:"
    )


@router.message(F.text == "⚠️ Просроченные")
async def filter_overdue(message: Message):
    await _filter_and_send(
        message,
        TaskFilter.overdue,
        "✅ Нет просроченных задач.",
        "⚠️ Просроченные задачи:",
    )


@router.message(F.text == "🔮 Запланированные")
async def filter_planned(message: Message):
    await _filter_and_send(
        message,
        TaskFilter.planned,
        "📭 Нет запланированных задач.",
        "🔮 Запланированные задачи:",
    )


@router.message(F.text == "🚫 Без дедлайна")
async def filter_no_deadline(message: Message):
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return
        try:
            tasks = await make_task_service(uow).filter_tasks(
                current_user=user,
                filter_user_group=FilterUserGroup.user,
                group_id=None,
                filter_type=TaskFilter.deadline_null,
                is_done=None,
                limit=100,
                offset=0,
            )
            if not tasks:
                await message.answer("📭 Нет задач без дедлайна.")
                return
            await message.answer("🚫 <b>Задачи без дедлайна:</b>\n", parse_mode="HTML")
            for task in tasks:
                status = _status_emoji(task)
                await message.answer(
                    f"{status} <b>{task.title}</b>\n🆔 ID: {task.id}", parse_mode="HTML"
                )
        except Exception as e:
            await message.answer(f"❌ Ошибка при получении задач: {str(e)}")


# ============ ПРОСМОТР ЗАДАЧИ ПО ID ============


@router.message(TaskFilters.waiting_for_task_id, F.text == "❌ Отмена")
async def cancel_task_id_input(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=task_filters_keyboard())


@router.message(EditTask.new_value, F.text == "❌ Отмена")
async def cancel_edit_task(message: Message, state: FSMContext):
    await state.set_state(EditTask.edit_type)
    data = await state.get_data()
    user_role = data.get("user_role", "user")
    kb = (
        task_edit_manager_keyboard()
        if user_role in ("admin", "manager")
        else task_edit_keyboard()
    )
    await message.answer("❌ Отменено.", reply_markup=kb)


@router.message(F.text == "🔍 По ID")
async def get_task_by_id_start(message: Message, state: FSMContext):
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            return
    await state.set_state(TaskFilters.waiting_for_task_id)
    await message.answer("🔍 Введите ID задачи:", reply_markup=cancel_keyboard())


@router.message(TaskFilters.waiting_for_task_id)
async def get_task_by_id(message: Message, state: FSMContext):
    try:
        assert message.text is not None
        task_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID (число).")
        return
    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            await state.clear()
            return
        try:
            # ← get_task(task_id, user) — без session
            task = await make_task_service(uow).get_task(task_id, user)
            status = _status_label(task)
            author = task.author.username if task.author else "Неизвестный"
            await message.answer(
                f"📋 <b>Задача #{task.id}</b>\n\n"
                f"<b>{task.title}</b>\n"
                f"📝 Описание: {task.description or 'Нет'}\n"
                f"📊 Статус: {status}\n"
                f"🎯 Приоритет: {'🔴 Критический' if task.priority and task.priority.value == 'critical' else '🟠 Высокий' if task.priority and task.priority.value == 'high' else '🔵 Средний' if task.priority and task.priority.value == 'medium' else '⚫ Низкий'}\n"
                f"📅 Дедлайн: {to_local(task.deadline)}\n"
                f"👤 Автор: {author}",
                parse_mode="HTML",
            )
            await state.update_data(task_id=task_id, user_role=user.role)
            await state.set_state(EditTask.edit_type)
            await message.answer(
                "✏️ Хотите редактировать задачу?",
                reply_markup=get_task_edit_keyboard(user),
            )
        except Exception:
            await message.answer(
                "❌ Задача не найдена или у вас нет прав доступа.",
                reply_markup=task_filters_keyboard(),
            )
            await state.clear()


# ============ РЕДАКТИРОВАНИЕ ЗАДАЧИ ============


@router.message(EditTask.edit_type)
async def edit_task_menu(message: Message, state: FSMContext):
    if message.text == "🔙 Назад в меню фильтры":
        await state.clear()
        await message.answer(
            "🔙 Вернулись в меню фильтры.", reply_markup=task_filters_keyboard()
        )
        return

    data = await state.get_data()
    task_id = data.get("task_id")

    if message.text == "✏️ Изменить название":
        await state.update_data(edit_type="title")
        await state.set_state(EditTask.new_value)
        await message.answer(
            "✏️ Введите новое название:", reply_markup=cancel_keyboard()
        )

    elif message.text == "📅 Изменить дедлайн":
        await state.update_data(edit_type="deadline")
        await state.set_state(EditTask.new_value)
        await message.answer(
            "📅 Введите новый дедлайн (ДД.ММ.ГГГГ ЧЧ:ММ) или 'нет' для удаления:",
            reply_markup=cancel_keyboard(),
        )

    # В edit_task_menu (EditTask.edit_type), после блока "📅 Изменить дедлайн":
    elif message.text == "🔄 Переназначить задачу":
        async with UnitOfWork(get_session_maker()) as uow:
            assert message.from_user is not None
            user = await uow.users.get_by_telegram_id(message.from_user.id)
            if not user or user.role not in ("admin", "manager"):
                await message.answer("❌ У вас нет прав для переназначения.")
                return
        await state.set_state(ReassignTask.assign_to)
        await message.answer(
            "👤 Кому переназначить задачу?", reply_markup=assign_to_keyboard()
        )

    elif message.text == "💬 Комментарии":
        async with UnitOfWork(get_session_maker()) as uow:
            assert message.from_user is not None
            user = await uow.users.get_by_telegram_id(message.from_user.id)
            if not user:
                await message.answer("❌ У вас нет доступа.")
                await state.clear()
                return
            try:
                if not task_id:
                    await message.answer("❌ Задача не найдена.")
                    await state.clear()
                    return
                task_id = int(task_id)
                # ← get_by_task(task_id, user) — без session
                comments = await make_comment_service(uow).get_by_task(task_id, user)
                if not comments:
                    await message.answer("📭 Нет комментариев к этой задаче.")
                else:
                    await message.answer(
                        f"💬 <b>Комментарии к задаче #{task_id}:</b>\n",
                        parse_mode="HTML",
                    )
                    for comment in comments:
                        author = (
                            comment.user.username if comment.user else "Неизвестный"
                        )
                        await message.answer(
                            f"👤 <b>{author}</b>\n💭 {comment.content}",
                            parse_mode="HTML",
                        )
                await state.update_data(task_id=task_id)
                await state.set_state(AddComment.action_choice)
                await message.answer(
                    "Что вы хотите сделать?", reply_markup=comments_action_keyboard()
                )
            except Exception as e:
                await message.answer(f"❌ Ошибка: {str(e)}")
                await state.clear()

    elif message.text in ("➡️ Статус вперёд", "⬅️ Статус назад"):
        _STATUS_ORDER = ["backlog", "todo", "in_progress", "review", "done"]
        _STATUS_LABEL = {
            "backlog": "📥 В очереди",
            "todo": "📋 Новая",
            "in_progress": "⚙️ В работе",
            "review": "👁 На проверке",
            "done": "✅ Выполнена",
        }
        direction = 1 if message.text == "➡️ Статус вперёд" else -1
        async with UnitOfWork(get_session_maker()) as uow:
            assert message.from_user is not None
            user = await uow.users.get_by_telegram_id(message.from_user.id)
            if not user:
                await message.answer("❌ У вас нет доступа.")
                await state.clear()
                return
            uow.set_audit_user(user.id)
            try:
                if not task_id:
                    await message.answer("❌ Задача не найдена.")
                    await state.clear()
                    return
                task_id = int(task_id)
                task = await make_task_service(uow).get_task(task_id, user)
                current = task.status.value if task.status else "todo"
                idx = _STATUS_ORDER.index(current)
                new_idx = max(0, min(len(_STATUS_ORDER) - 1, idx + direction))
                if new_idx == idx:
                    edge = "последний" if direction == 1 else "первый"
                    await message.answer(f"ℹ️ Это уже {edge} статус.")
                    await state.set_state(EditTask.edit_type)
                    await message.answer(
                        "Выберите действие:", reply_markup=get_task_edit_keyboard(user)
                    )
                    return
                new_status = TaskStatus(_STATUS_ORDER[new_idx])
                await make_task_service(uow).update_task_status(
                    task_id, new_status, user
                )
                await uow.commit()
                label = _STATUS_LABEL[_STATUS_ORDER[new_idx]]
                await notify_task_updated(
                    task_id,
                    {"status": new_status.value},
                    editor_telegram_id=message.from_user.id,
                )
                await message.answer(f"Статус обновлён: {label}")
                await state.set_state(EditTask.edit_type)
                await message.answer(
                    "Выберите действие:", reply_markup=get_task_edit_keyboard(user)
                )
            except Exception as e:
                await message.answer(f"❌ Ошибка: {str(e)}")
                await state.clear()

    elif message.text == "🗑 Удалить задачу":
        async with UnitOfWork(get_session_maker()) as uow:
            assert message.from_user is not None
            user = await uow.users.get_by_telegram_id(message.from_user.id)
            if not user:
                await message.answer("❌ У вас нет доступа.")
                await state.clear()
                return
            uow.set_audit_user(user.id)
            try:
                if not task_id:
                    await message.answer("❌ Задача не найдена.")
                    await state.clear()
                    return
                task_id = int(task_id)
                await make_task_service(uow).delete_task(task_id, user)
                # keyboard = (main_menu_admin() if user.role == "admin" else main_menu_user())
                keyboard = get_main_menu(user)
                await message.answer(
                    f"🗑 Задача #{task_id} перемещена в корзину.",
                    reply_markup=keyboard,
                )
                await state.clear()
            except Exception as e:
                await message.answer(f"❌ Ошибка: {str(e)}")
                await state.clear()


@router.message(ReassignTask.assign_to)
async def reassign_task_assign(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.set_state(EditTask.edit_type)
        data = await state.get_data()
        user_role = data.get("user_role", "user")
        kb = (
            task_edit_manager_keyboard()
            if user_role in ("admin", "manager")
            else task_edit_keyboard()
        )
        await message.answer("❌ Отменено.", reply_markup=kb)
        return
    if message.text == "👤 Пользователю":
        async with UnitOfWork(get_session_maker()) as uow:
            users = await uow.users.get_all()
        text = "👤 Введите ID пользователя:\n\n" + "".join(
            f"🆔 {u.id} — {u.username}\n" for u in users
        )
        await state.set_state(ReassignTask.select_user)
        await message.answer(text, reply_markup=cancel_keyboard())
    elif message.text == "👥 Группе":
        async with UnitOfWork(get_session_maker()) as uow:
            groups = await uow.groups.get_all()
        text = "👥 Введите ID группы:\n\n" + "".join(
            f"🆔 {g.id} — {g.name}\n" for g in groups
        )
        await state.set_state(ReassignTask.select_group)
        await message.answer(text, reply_markup=cancel_keyboard())
    elif message.text == "🚫 Без назначения":
        await _do_reassign(message, state, user_id=None, group_id=None)


@router.message(ReassignTask.select_user)
async def reassign_select_user(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.set_state(ReassignTask.assign_to)
        await message.answer("❌ Отменено.", reply_markup=assign_to_keyboard())
        return
    try:
        assert message.text is not None
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID.")
        return
    await _do_reassign(message, state, user_id=user_id, group_id=None)


@router.message(ReassignTask.select_group)
async def reassign_select_group(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.set_state(ReassignTask.assign_to)
        await message.answer("❌ Отменено.", reply_markup=assign_to_keyboard())
        return
    try:
        assert message.text is not None
        group_id = int(message.text)
    except ValueError:
        await message.answer("❌ Введите корректный ID.")
        return
    await _do_reassign(message, state, user_id=None, group_id=group_id)


async def _do_reassign(
    message: Message, state: FSMContext, user_id: int | None, group_id: int | None
):
    data = await state.get_data()
    task_id: int | None = data.get("task_id")

    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            await state.clear()
            return

        uow.set_audit_user(user.id)

        try:
            if not task_id:
                await message.answer("❌ Задача не найдена.")
                await state.clear()
                return
            task_id = int(task_id)
            task_repo = TaskRepository(uow.session)
            task = await task_repo.get_by_id(task_id)
            if not task:
                await message.answer("❌ Задача не найдена.")
                await state.clear()
                return

            task.user_id = user_id
            task.group_id = group_id
            await task_repo.update(task)
            await notify_task_assigned(task_id)
            await message.answer("✅ Задача переназначена!")

        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
            await state.clear()
            return

    await state.set_state(EditTask.edit_type)
    kb = (
        task_edit_manager_keyboard()
        if user.role in ("admin", "manager")
        else task_edit_keyboard()
    )
    await message.answer("Выберите действие:", reply_markup=kb)


@router.message(EditTask.new_value)
async def edit_task_new_value(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("task_id")
    edit_type = data.get("edit_type")

    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            await state.clear()
            return

        uow.set_audit_user(user.id)

        # keyboard = main_menu_admin() if user.role == "admin" else main_menu_user()
        keyboard = get_main_menu(user)

        try:
            if edit_type == "title":
                if not task_id:
                    await message.answer("❌ Задача не найдена.")
                    await state.clear()
                    return
                task_id = int(task_id)
                await make_task_service(uow).update_task(
                    task_id, SpisokUpdate(title=message.text), user
                )
                await notify_task_updated(task_id, {"title": message.text})
                await message.answer(
                    f"✅ Название изменено на: <b>{message.text}</b>",
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
            elif edit_type == "deadline":
                assert message.text is not None
                if message.text.lower() == "нет":
                    if not task_id:
                        await message.answer("❌ Задача не найдена.")
                        await state.clear()
                        return
                    task_id = int(task_id)
                    await make_task_service(uow).update_task(
                        task_id, SpisokUpdate(deadline=None), user
                    )
                    await notify_task_updated(task_id, {"deadline": None})
                    await message.answer("✅ Дедлайн удален!", reply_markup=keyboard)
                else:
                    try:
                        assert message.text is not None
                        new_deadline = datetime.strptime(
                            message.text, "%d.%m.%Y %H:%M"
                        ).replace(tzinfo=LOCAL_TZ)
                        if not task_id:
                            await message.answer("❌ Задача не найдена.")
                            await state.clear()
                            return
                        task_id = int(task_id)
                        await make_task_service(uow).update_task(
                            task_id, SpisokUpdate(deadline=new_deadline), user
                        )
                        await notify_task_updated(task_id, {"deadline": new_deadline})
                        await message.answer(
                            f"✅ Дедлайн изменен на: <b>{message.text}</b>",
                            parse_mode="HTML",
                            reply_markup=keyboard,
                        )
                    except ValueError:
                        await message.answer(
                            "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ ЧЧ:ММ"
                        )
                        return
            await state.set_state(EditTask.edit_type)
            data = await state.get_data()
            user_role = data.get("user_role", "user")
            kb = (
                task_edit_manager_keyboard()
                if user_role in ("admin", "manager")
                else task_edit_keyboard()
            )
            await message.answer("Выберите действие:", reply_markup=kb)
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=keyboard)
            await state.clear()


# ============ КОММЕНТАРИИ К ЗАДАЧАМ ============


@router.message(AddComment.action_choice)
async def comments_action_choice(message: Message, state: FSMContext):
    if message.text == "🔙 Назад в меню редактирования":
        await state.set_state(EditTask.edit_type)
        data = await state.get_data()
        user_role = data.get("user_role", "user")
        kb = (
            task_edit_manager_keyboard()
            if user_role in ("admin", "manager")
            else task_edit_keyboard()
        )
        await message.answer(
            "🔙 Возвращаемся к редактированию задачи.", reply_markup=kb
        )
        return
    if message.text == "💬 Добавить комментарий":
        await state.set_state(AddComment.comment_text)
        await message.answer(
            "💬 Введите текст комментария:", reply_markup=cancel_keyboard()
        )
        return
    await message.answer("❌ Выберите действие из меню.")


@router.message(AddComment.comment_text)
async def add_task_comment(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.set_state(EditTask.edit_type)
        data = await state.get_data()
        user_role = data.get("user_role", "user")
        kb = (
            task_edit_manager_keyboard()
            if user_role in ("admin", "manager")
            else task_edit_keyboard()
        )  # ← добавить
        await message.answer(
            "❌ Отменено. Возвращаемся к редактированию задачи.",
            reply_markup=kb,  # ← было task_edit_keyboard()
        )
        return

    data = await state.get_data()
    task_id = data.get("task_id")

    async with UnitOfWork(get_session_maker()) as uow:
        assert message.from_user is not None
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ У вас нет доступа.")
            await state.clear()
            return

        uow.set_audit_user(user.id)

        try:
            assert message.text and task_id is not None
            comment = await make_comment_service(uow).add_comment(
                task_id,
                CommentCreate(content=message.text),
                user,
            )
            await message.answer(
                f"✅ Комментарий добавлен!\n\n💭 {comment.content}", parse_mode="HTML"
            )
            await state.set_state(AddComment.action_choice)
            await message.answer(
                "Что ещё хотите сделать с комментариями?",
                reply_markup=comments_action_keyboard(),
            )
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
            await state.clear()
