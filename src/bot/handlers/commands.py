"""
Текстовые команды бота — быстрые действия без диалогов.

Уровень 1: /done, /undone, /task, /del
Уровень 2: /my, /today, /overdue, /stats
Уровень 3: /new  (парсинг строки через |)
Уровень 4: /find, /group
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message

from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.models.task import SpisokModel, TaskPriority, TaskStatus
from src.repositories.groups_repository import GroupRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.schemas.task import FilterUserGroup, TaskFilter
from src.services.notifications import notify_task_assigned
from src.services.task_service import TaskService

LOCAL_TZ = ZoneInfo("Europe/Kiev")

router = Router()


# ── Фабрика сервиса (та же что в tasks.py) ────────────────────────────────────


def make_task_service(uow: UnitOfWork) -> TaskService:
    return TaskService(
        task_repo=TaskRepository(uow.session),
        user_repo=UserRepository(uow.session),
        group_repo=GroupRepository(uow.session),
        session=uow.session,
    )


# ── Форматирование ────────────────────────────────────────────────────────────

_PRIORITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🔵",
    "low": "⚪",
}


def _priority_emoji(task) -> str:
    if not task.priority:
        return "⚪"
    return _PRIORITY_EMOJI.get(task.priority.value, "⚪")


def _fmt_deadline(task) -> str:
    if not task.deadline:
        return "без дедлайна"
    dt = task.deadline
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M")


_STATUS_EMOJI = {
    "done": "✅",
    "in_progress": "⚙️",
    "review": "👁",
    "todo": "📋",
    "backlog": "📥",
}


def _fmt_short(task) -> str:
    key = task.status.value if task.status else "todo"
    status = _STATUS_EMOJI.get(key, "⏳")
    return f"{status} <b>{task.title}</b>\n{_priority_emoji(task)} | 📅 {_fmt_deadline(task)} | 🆔 {task.id}"


def _fmt_full(task) -> str:
    _status_labels = {
        "done": "✅ Выполнена",
        "in_progress": "⚙️ В работе",
        "review": "👁 На проверке",
        "todo": "📋 Новая",
        "backlog": "📥 В очереди",
    }
    key = task.status.value if task.status else "todo"
    status = _status_labels.get(key, "⏳ Неизвестно")
    author = task.author.username if task.author else "Неизвестный"
    priority_labels = {
        "critical": "🔴 Критический",
        "high": "🟠 Высокий",
        "medium": "🔵 Средний",
        "low": "⚪ Низкий",
    }
    prio = priority_labels.get(task.priority.value if task.priority else "", "⚪ Низкий")
    return (
        f"📋 <b>Задача #{task.id}</b>\n\n"
        f"<b>{task.title}</b>\n"
        f"📝 {task.description or 'Нет описания'}\n"
        f"📊 {status}\n"
        f"🎯 {prio}\n"
        f"📅 Дедлайн: {_fmt_deadline(task)}\n"
        f"👤 Автор: {author}"
    )


# ── Общие хелперы ─────────────────────────────────────────────────────────────


async def _get_user(uow: UnitOfWork, message: Message):
    """Возвращает пользователя или None (с ответом об ошибке)."""
    assert message.from_user is not None
    user = await uow.users.get_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("❌ У вас нет доступа.")
    return user


def _parse_id(args: str | None) -> int | None:
    try:
        return int((args or "").strip())
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# УРОВЕНЬ 1 — быстрые действия
# ══════════════════════════════════════════════════════════════════════════════


@router.message(Command("done"))
async def cmd_done(message: Message, command: CommandObject):
    """/done 42 — отметить задачу #42 как выполненную."""
    task_id = _parse_id(command.args)
    if not task_id:
        await message.answer("⚠️ Укажите ID задачи: <code>/done 42</code>", parse_mode="HTML")
        return

    async with UnitOfWork(get_session_maker()) as uow:
        user = await _get_user(uow, message)
        if not user:
            return
        uow.set_audit_user(user.id)
        try:
            await make_task_service(uow).update_task_status(task_id, TaskStatus.done, user)
            await uow.commit()
            await message.answer(
                f"✅ Задача <b>#{task_id}</b> отмечена как выполненная!",
                parse_mode="HTML",
            )
        except Exception as e:
            await message.answer(f"❌ Не удалось: {e}")


@router.message(Command("undone"))
async def cmd_undone(message: Message, command: CommandObject):
    """/undone 42 — снять отметку выполнения."""
    task_id = _parse_id(command.args)
    if not task_id:
        await message.answer("⚠️ Укажите ID задачи: <code>/undone 42</code>", parse_mode="HTML")
        return

    async with UnitOfWork(get_session_maker()) as uow:
        user = await _get_user(uow, message)
        if not user:
            return
        uow.set_audit_user(user.id)
        try:
            await make_task_service(uow).update_task_status(task_id, TaskStatus.todo, user)
            await uow.commit()
            await message.answer(
                f"⏳ Задача <b>#{task_id}</b> переведена в статус «Новая».",
                parse_mode="HTML",
            )
        except Exception as e:
            await message.answer(f"❌ Не удалось: {e}")


@router.message(Command("task"))
async def cmd_task(message: Message, command: CommandObject):
    """/task 42 — показать задачу #42 с деталями."""
    task_id = _parse_id(command.args)
    if not task_id:
        await message.answer("⚠️ Укажите ID задачи: <code>/task 42</code>", parse_mode="HTML")
        return

    async with UnitOfWork(get_session_maker()) as uow:
        user = await _get_user(uow, message)
        if not user:
            return
        try:
            task = await make_task_service(uow).get_task(task_id, user)
            await message.answer(_fmt_full(task), parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Не удалось: {e}")


@router.message(Command("del"))
async def cmd_del(message: Message, command: CommandObject):
    """/del 42 — переместить задачу #42 в корзину."""
    task_id = _parse_id(command.args)
    if not task_id:
        await message.answer("⚠️ Укажите ID задачи: <code>/del 42</code>", parse_mode="HTML")
        return

    async with UnitOfWork(get_session_maker()) as uow:
        user = await _get_user(uow, message)
        if not user:
            return
        uow.set_audit_user(user.id)
        try:
            # delete_task делает session.commit() внутри себя
            await make_task_service(uow).delete_task(task_id, user)
            await message.answer(f"🗑 Задача <b>#{task_id}</b> перемещена в корзину.", parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Не удалось: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# УРОВЕНЬ 2 — просмотр и статистика
# ══════════════════════════════════════════════════════════════════════════════


async def _send_filtered(
    message: Message,
    filter_type: TaskFilter,
    header: str,
    empty: str,
):
    """Хелпер для /today и /overdue."""
    async with UnitOfWork(get_session_maker()) as uow:
        user = await _get_user(uow, message)
        if not user:
            return
        tasks = await make_task_service(uow).filter_tasks(
            current_user=user,
            filter_user_group=FilterUserGroup.user,
            group_id=None,
            filter_type=filter_type,
            is_done=None,
            limit=10,
            offset=0,
        )
    if not tasks:
        await message.answer(empty)
        return
    lines = [f"<b>{header}</b>"] + [_fmt_short(t) for t in tasks]
    await message.answer("\n\n".join(lines), parse_mode="HTML")


@router.message(Command("my"))
async def cmd_my(message: Message):
    """/my — первые 10 моих задач."""
    async with UnitOfWork(get_session_maker()) as uow:
        user = await _get_user(uow, message)
        if not user:
            return
        tasks = await make_task_service(uow).filter_tasks(
            current_user=user,
            filter_user_group=FilterUserGroup.user,
            group_id=None,
            filter_type=None,
            is_done=None,
            limit=10,
            offset=0,
        )
    if not tasks:
        await message.answer("📭 У вас нет задач.")
        return
    lines = ["<b>📋 Мои задачи:</b>"] + [_fmt_short(t) for t in tasks]
    await message.answer("\n\n".join(lines), parse_mode="HTML")


@router.message(Command("today"))
async def cmd_today(message: Message):
    """/today — задачи на сегодня."""
    await _send_filtered(message, TaskFilter.today, "📅 Задачи на сегодня:", "📭 Нет задач на сегодня.")


@router.message(Command("overdue"))
async def cmd_overdue(message: Message):
    """/overdue — просроченные задачи."""
    await _send_filtered(
        message,
        TaskFilter.overdue,
        "⚠️ Просроченные задачи:",
        "✅ Просроченных задач нет.",
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """/stats — статистика через get_user_stats."""
    async with UnitOfWork(get_session_maker()) as uow:
        user = await _get_user(uow, message)
        if not user:
            return
        s = await make_task_service(uow).get_user_stats(user.id)

    recent_lines = ""
    if s["tasks"]:
        items = []
        for t in s["tasks"][:5]:
            st = "✅" if t["status"] == "done" else "⏳"
            items.append(f"  {st} {t['title']} (#{t['id']})")
        recent_lines = "\n\n<b>🕐 Последние задачи:</b>\n" + "\n".join(items)

    await message.answer(
        f"📊 <b>Ваша статистика</b>\n\n"
        f"<b>Назначено мне:</b>\n"
        f"📌 Всего: <b>{s['total']}</b>\n"
        f"✅ Выполнено: <b>{s['done']}</b>\n"
        f"⏳ Не выполнено: <b>{s['pending']}</b>\n"
        f"📈 Прогресс: <b>{s['percent']}%</b>\n\n"
        f"<b>Я создал:</b>\n"
        f"📌 Всего: <b>{s['a_total']}</b>\n"
        f"✅ Выполнено: <b>{s['a_done']}</b>"
        f"{recent_lines}",
        parse_mode="HTML",
    )


# ══════════════════════════════════════════════════════════════════════════════
# УРОВЕНЬ 3 — создание одной командой
# ══════════════════════════════════════════════════════════════════════════════


def _parse_deadline(raw: str) -> datetime | None:
    """ДД.ММ.ГГГГ ЧЧ:ММ  или  ДД.ММ.ГГГГ (тогда время = 09:00)."""
    raw = raw.strip()
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            if fmt == "%d.%m.%Y":
                dt = dt.replace(hour=9, minute=0)
            return dt  # без tzinfo — как в остальном коде бота
        except ValueError:
            continue
    return None


@router.message(Command("new"))
async def cmd_new(message: Message, command: CommandObject):
    """/new Название | дедлайн | @username

    Примеры:
      /new Купить молоко
      /new Сдать отчёт | 25.06.2025 18:00
      /new Позвонить клиенту | 30.06.2025 | @ivan
    """
    raw = (command.args or "").strip()
    if not raw:
        await message.answer(
            "⚠️ Укажите название задачи.\n\n"
            "<b>Примеры:</b>\n"
            "<code>/new Купить молоко</code>\n"
            "<code>/new Сдать отчёт | 25.06.2025 18:00</code>\n"
            "<code>/new Позвонить клиенту | 30.06.2025 | @ivan</code>",
            parse_mode="HTML",
        )
        return

    parts = [p.strip() for p in raw.split("|")]
    title = parts[0]
    deadline: datetime | None = None
    assigned_user_id: int | None = None
    assigned_username: str | None = None

    if len(parts) >= 2 and parts[1]:
        deadline = _parse_deadline(parts[1])
        if not deadline:
            await message.answer(
                f"❌ Не удалось распознать дату: <code>{parts[1]}</code>\n"
                "Используйте формат: <code>ДД.ММ.ГГГГ ЧЧ:ММ</code> или <code>ДД.ММ.ГГГГ</code>",
                parse_mode="HTML",
            )
            return

    if len(parts) >= 3 and parts[2]:
        assigned_username = parts[2].lstrip("@")

    async with UnitOfWork(get_session_maker()) as uow:
        user = await _get_user(uow, message)
        if not user:
            return
        uow.set_audit_user(user.id)

        if assigned_username:
            target = await uow.users.get_by_username(assigned_username)
            if not target:
                await message.answer(
                    f"❌ Пользователь <code>@{assigned_username}</code> не найден.",
                    parse_mode="HTML",
                )
                return
            assigned_user_id = target.id

        task = SpisokModel(
            title=title,
            description=None,
            user_id=assigned_user_id,
            group_id=None,
            deadline=deadline,
            author_id=user.id,
            priority=TaskPriority("medium"),
        )
        created = await uow.tasks.create(task)
        await uow.session.flush()
        asyncio.create_task(notify_task_assigned(created.id))
        await uow.commit()

    deadline_str = deadline.strftime("%d.%m.%Y %H:%M") if deadline else "не задан"
    assignee_str = f"@{assigned_username}" if assigned_username else "без назначения"

    await message.answer(
        f"✅ Задача создана!\n\n"
        f"📋 <b>{created.title}</b>\n"
        f"📅 Дедлайн: {deadline_str}\n"
        f"👤 Назначена: {assignee_str}\n"
        f"🆔 ID: {created.id}",
        parse_mode="HTML",
    )


# ══════════════════════════════════════════════════════════════════════════════
# УРОВЕНЬ 4 — поиск и фильтры
# ══════════════════════════════════════════════════════════════════════════════


@router.message(Command("find"))
async def cmd_find(message: Message, command: CommandObject):
    """/find отчёт — поиск задач по части названия/описания."""
    query = (command.args or "").strip()
    if not query:
        await message.answer("⚠️ Укажите текст для поиска: <code>/find отчёт</code>", parse_mode="HTML")
        return

    async with UnitOfWork(get_session_maker()) as uow:
        user = await _get_user(uow, message)
        if not user:
            return

        # Берём все задачи пользователя и фильтруем по подстроке в памяти.
        # filter_tasks не поддерживает search_query — используем TaskFilter.all
        # и ищем сами. Для больших БД стоит добавить репозиторный метод поиска.
        all_tasks = await make_task_service(uow).filter_tasks(
            current_user=user,
            filter_user_group=FilterUserGroup.user,
            group_id=None,
            filter_type=None,
            is_done=None,
            limit=1000,
            offset=0,
        )

    q = query.lower()
    tasks = [t for t in all_tasks if q in (t.title or "").lower() or q in (t.description or "").lower()][:20]

    if not tasks:
        await message.answer(f"🔍 По запросу «{query}» задач не найдено.")
        return

    lines = [f"🔎 <b>Результаты поиска «{query}»:</b>"] + [_fmt_short(t) for t in tasks]
    await message.answer("\n\n".join(lines), parse_mode="HTML")


@router.message(Command("group"))
async def cmd_group(message: Message, command: CommandObject):
    """/group 3 — задачи группы #3."""
    group_id = _parse_id(command.args)
    if not group_id:
        await message.answer("⚠️ Укажите ID группы: <code>/group 3</code>", parse_mode="HTML")
        return

    async with UnitOfWork(get_session_maker()) as uow:
        user = await _get_user(uow, message)
        if not user:
            return

        group = await uow.groups.get_by_id(group_id)
        if not group:
            await message.answer(f"❌ Группа #{group_id} не найдена.")
            return

        try:
            tasks = await make_task_service(uow).filter_tasks(
                current_user=user,
                filter_user_group=FilterUserGroup.group,
                group_id=group_id,
                filter_type=None,
                is_done=None,
                limit=20,
                offset=0,
            )
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
            return

    if not tasks:
        await message.answer(f"📭 В группе «{group.name}» нет задач.")
        return

    lines = [f"<b>👥 Задачи группы «{group.name}»:</b>"] + [_fmt_short(t) for t in tasks]
    await message.answer("\n\n".join(lines), parse_mode="HTML")


@router.message(Command("voice"))
async def cmd_voice_help(message: Message):
    """Шпаргалка по голосовым командам."""
    text = (
        "🎤 <b>Голосовые команды — шпаргалка</b>\n"
        "\n"
        "Отправь голосовое — бот сам поймёт что нужно сделать.\n"
        "Бот помнит контекст: можно говорить «эту же», «её», «ту задачу».\n"
        "\n"
        "📌 <b>Создать задачу</b>\n"
        "<i>«позвонить Илье завтра до 12, срочно»</i>\n"
        "<i>«подготовить отчёт до пятницы»</i>\n"
        "<i>«купить молоко и назначить на maksim»</i>\n"
        "\n"
        "🔍 <b>Найти задачи</b>\n"
        "<i>«найди задачу про Илью»</i>\n"
        "<i>«покажи просроченные задачи»</i>\n"
        "<i>«какие задачи в работе»</i>\n"
        "<i>«покажи срочные»</i>\n"
        "\n"
        "✅ <b>Изменить статус</b>\n"
        "<i>«отметь задачу про звонок как выполненную»</i>\n"
        "<i>«закрой задачу про отчёт»</i>\n"
        "<i>«задача про договор в работе»</i>\n"
        "<i>«верни задачу про встречу»</i>\n"
        "\n"
        "🔴 <b>Изменить приоритет</b>\n"
        "<i>«сделай задачу про отчёт срочной»</i>\n"
        "<i>«задача про встречу не срочная»</i>\n"
        "\n"
        "👤 <b>Назначить исполнителя</b>\n"
        "<i>«назначь задачу про договор на maksim»</i>\n"
        "<i>«переназначь задачу про отчёт на aleksey»</i>\n"
        "\n"
        "📝 <b>Изменить описание</b>\n"
        "<i>«добавь описание к задаче про звонок: уточнить детали»</i>\n"
        "<i>«обнови описание задачи про отчёт»</i>\n"
        "\n"
        "🔀 <b>Составные команды</b> (выполняются за один раз)\n"
        "<i>«найди просроченные и покажи»</i>\n"
        "<i>«создай задачу позвонить Марине и назначь на меня»</i>\n"
        "<i>«назначь эту же задачу на меня и повысь приоритет»</i>\n"
        "\n"
        "🧠 <b>Контекст диалога</b> (бот помнит 10 последних сообщений)\n"
        "<i>«найди задачу про Илью»</i>\n"
        "<i>→ «сделай её срочной»</i>\n"
        "<i>→ «назначь на maksim»</i>\n"
        "\n"
        "💡 <b>Подсказка:</b> если команда не распознана как поиск/изменение — "
        "бот автоматически <b>создаст задачу</b>."
    )
    await message.answer(text, parse_mode="HTML")
