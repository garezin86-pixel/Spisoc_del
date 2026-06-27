"""
src/bot/handlers/voice.py

Голосовой ассистент с memory (Redis) и tool calling (Groq).
Поддерживает составные команды и контекст диалога.
"""

import io
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select, or_, and_

from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.models.task import SpisokModel, TaskPriority, TaskStatus
from src.models.user import UserModel
from src.services.voice_ai import process_voice_message
from src.services.chat_memory import get_history, add_message
from src.services.notifications import notify_task_assigned, notify_task_updated

logger = logging.getLogger(__name__)
router = Router()
LOCAL_TZ = ZoneInfo("Europe/Kiev")

PRIORITY_EMOJI = {"low": "⚪", "medium": "🔵", "high": "🟠", "critical": "🔴"}
PRIORITY_LABEL = {
    "low": "Низкий",
    "medium": "Средний",
    "high": "Высокий",
    "critical": "Критический",
}
STATUS_LABEL = {
    "todo": "📋 Новая",
    "in_progress": "⚙️ В работе",
    "review": "👁 На проверке",
    "done": "✅ Выполнена",
    "backlog": "📥 В очереди",
}


class VoiceConfirm(StatesGroup):
    waiting = State()  # ждём подтверждения набора действий


# ── Хелперы ───────────────────────────────────────────────────────────────────


def _kb_confirm(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выполнить", callback_data=f"vc:ok:{uid}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"vc:no:{uid}"),
            ]
        ]
    )


async def _search_tasks(session, user_id: int, query: str) -> list[SpisokModel]:
    words = [w.strip() for w in query.split() if len(w.strip()) > 2]
    if not words:
        words = [query.strip()]
    conditions = [SpisokModel.title.ilike(f"%{w}%") for w in words]
    result = await session.execute(
        select(SpisokModel)
        .where(
            and_(
                SpisokModel.deleted_at.is_(None),
                or_(SpisokModel.user_id == user_id, SpisokModel.author_id == user_id),
                or_(*conditions),
            )
        )
        .order_by(SpisokModel.created_at.desc())
        .limit(5)
    )
    return list(result.scalars().all())


async def _search_users(session, query: str) -> list[UserModel]:
    words = [w.strip() for w in query.split() if len(w.strip()) > 1]
    if not words:
        words = [query.strip()]
    conditions = [UserModel.username.ilike(f"%{w}%") for w in words]
    result = await session.execute(select(UserModel).where(or_(*conditions)).limit(5))
    return list(result.scalars().all())


def _parse_deadline(deadline_str: str | None, time_str: str | None) -> datetime | None:
    if not deadline_str:
        return None
    try:
        h, m = (23, 59)
        if time_str:
            try:
                t = datetime.strptime(time_str, "%H:%M")
                h, m = t.hour, t.minute
            except ValueError:
                pass
        return datetime.strptime(deadline_str, "%Y-%m-%d").replace(
            hour=h, minute=m, tzinfo=LOCAL_TZ
        )
    except ValueError:
        return None


def _fmt_task(task: SpisokModel) -> str:
    priority = task.priority.value if task.priority else "medium"
    status = task.status.value if task.status else "todo"
    return (
        f"{PRIORITY_EMOJI.get(priority, '🔵')} <b>{task.title}</b> "
        f"— {STATUS_LABEL.get(status, status)} [#{task.id}]"
    )


# ── Выполнение tool calls ─────────────────────────────────────────────────────


async def _execute_tool(
    tool_name: str,
    args: dict,
    user_id: int,
    session,
) -> str:
    """Выполняет один tool call, возвращает текстовый результат."""

    if tool_name == "text_response":
        return args.get("text", "")

    if tool_name == "create_task":
        priority_val = args.get("priority", "medium")
        try:
            priority = TaskPriority(priority_val)
        except ValueError:
            priority = TaskPriority.medium

        deadline = _parse_deadline(args.get("deadline"), args.get("deadline_time"))

        # Исполнитель если указан
        assignee_id = user_id
        if args.get("assignee_username"):
            users = await _search_users(session, args["assignee_username"])
            if users:
                assignee_id = users[0].id

        session.info["audit_user_id"] = user_id
        task = SpisokModel(
            title=args["title"][:255],
            description=args.get("description"),
            priority=priority,
            status=TaskStatus.todo,
            deadline=deadline,
            user_id=assignee_id,
            author_id=user_id,
        )
        session.add(task)
        await session.flush()
        await notify_task_assigned(task.id)

        emoji = PRIORITY_EMOJI.get(priority.value, "🔵")
        dl = f"\n📅 {args['deadline']}" if args.get("deadline") else ""
        assignee_str = (
            f"\n👤 → {args['assignee_username']}"
            if args.get("assignee_username")
            else ""
        )
        return f"✅ Создана: <b>{task.title}</b>\n{emoji} {PRIORITY_LABEL.get(priority.value, priority.value)}{dl}{assignee_str}"

    if tool_name == "get_tasks":
        from sqlalchemy import and_, or_
        from datetime import datetime, timezone

        conditions = [
            SpisokModel.deleted_at.is_(None),
            or_(SpisokModel.user_id == user_id, SpisokModel.author_id == user_id),
        ]

        if args.get("search"):
            words = [w for w in args["search"].split() if len(w) > 2]
            if words:
                conditions.append(
                    or_(*[SpisokModel.title.ilike(f"%{w}%") for w in words])
                )

        if args.get("status"):
            try:
                conditions.append(SpisokModel.status == TaskStatus(args["status"]))
            except ValueError:
                pass

        if args.get("priority"):
            try:
                conditions.append(
                    SpisokModel.priority == TaskPriority(args["priority"])
                )
            except ValueError:
                pass

        if args.get("overdue"):
            now = datetime.now(timezone.utc)
            conditions.append(SpisokModel.deadline < now)
            conditions.append(SpisokModel.status != TaskStatus.done)

        result = await session.execute(
            select(SpisokModel)
            .where(and_(*conditions))
            .order_by(SpisokModel.created_at.desc())
            .limit(10)
        )
        tasks = list(result.scalars().all())

        if not tasks:
            return "🔍 Задачи не найдены."

        lines = [f"🔍 Найдено: {len(tasks)}"]
        for t in tasks:
            lines.append(_fmt_task(t))
        return "\n".join(lines)

    if tool_name == "update_task_status":
        tasks = await _search_tasks(session, user_id, args.get("search", ""))
        if not tasks:
            return f"🔍 Задача «{args.get('search')}» не найдена."
        task = tasks[0]
        try:
            session.info["audit_user_id"] = user_id
            task.status = TaskStatus(args["status"])
            await session.flush()
            await notify_task_updated(task.id, {"status": args["status"]})
        except ValueError:
            return f"❌ Неизвестный статус: {args['status']}"
        label = STATUS_LABEL.get(args["status"], args["status"])
        return f"✅ <b>{task.title}</b>\n→ {label}"

    if tool_name == "update_task_priority":
        tasks = await _search_tasks(session, user_id, args.get("search", ""))
        if not tasks:
            return f"🔍 Задача «{args.get('search')}» не найдена."
        task = tasks[0]
        try:
            session.info["audit_user_id"] = user_id
            task.priority = TaskPriority(args["priority"])
            await session.flush()
            await notify_task_updated(task.id, {"priority": args["priority"]})
        except ValueError:
            return f"❌ Неизвестный приоритет: {args['priority']}"
        emoji = PRIORITY_EMOJI.get(args["priority"], "🔵")
        label = PRIORITY_LABEL.get(args["priority"], args["priority"])
        return f"✅ <b>{task.title}</b>\n→ {emoji} {label}"

    if tool_name == "assign_task":
        tasks = await _search_tasks(session, user_id, args.get("search", ""))
        if not tasks:
            return f"🔍 Задача «{args.get('search')}» не найдена."
        task = tasks[0]
        users = await _search_users(session, args.get("assignee_username", ""))
        if not users:
            return f"🔍 Пользователь «{args.get('assignee_username')}» не найден."
        assignee = users[0]
        session.info["audit_user_id"] = user_id
        task.user_id = assignee.id
        await session.flush()
        await notify_task_assigned(task.id)
        return f"✅ <b>{task.title}</b>\n→ 👤 @{assignee.username}"

    if tool_name == "update_task_description":
        tasks = await _search_tasks(session, user_id, args.get("search", ""))
        if not tasks:
            return f"🔍 Задача «{args.get('search')}» не найдена."

        task = tasks[0]

        session.info["audit_user_id"] = user_id
        task.description = args["description"]

        await session.flush()

        await notify_task_updated(task.id, {"description": args["description"]})

        return f"📝 <b>{task.title}</b>\n→ описание обновлено"

    return f"❓ Неизвестная команда: {tool_name}"


# ── Главный обработчик ────────────────────────────────────────────────────────


@router.message(F.voice)
async def handle_voice(message: Message, state: FSMContext, bot: Bot):
    assert message.from_user is not None
    tg_id = message.from_user.id

    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(tg_id)
        if not user:
            await message.answer("❌ Сначала зарегистрируйтесь через /start")
            return
        user_id = user.id

    status_msg = await message.answer("🎤 Слушаю…")

    try:
        voice = message.voice
        assert voice is not None
        file = await bot.get_file(voice.file_id)
        if not file.file_path:
            raise ValueError("file_path is None")
        buf = io.BytesIO()
        await bot.download_file(file.file_path, destination=buf)

        # Загружаем историю из Redis
        history = await get_history(user_id)

        await status_msg.edit_text("🧠 Обрабатываю…")
        transcript, tool_calls = await process_voice_message(buf.getvalue(), history)

    except Exception as e:
        logger.exception("Voice processing error: %s", e)
        await status_msg.edit_text(
            "❌ Не удалось обработать голосовое. Попробуйте ещё раз."
        )
        return

    # Сохраняем запрос пользователя в память
    await add_message(user_id, "user", transcript)

    uid = str(tg_id)

    # Если только text_response — просто отвечаем без подтверждения
    if len(tool_calls) == 1 and tool_calls[0]["name"] == "text_response":
        resp = tool_calls[0]["arguments"].get("text", "")
        await status_msg.edit_text(
            f"🎤 <i>{transcript}</i>\n\n{resp}",
            parse_mode="HTML",
        )
        await add_message(user_id, "assistant", resp)
        return

    # Формируем превью действий для подтверждения
    lines = [f"🎤 <i>{transcript}</i>\n", "📋 <b>Выполнить:</b>"]
    for tc in tool_calls:
        name = tc["name"]
        args = tc["arguments"]
        if name == "create_task":
            priority = args.get("priority", "medium")
            lines.append(
                f"  ➕ Создать: <b>{args.get('title', '?')}</b> "
                f"{PRIORITY_EMOJI.get(priority, '🔵')}"
            )
        elif name == "get_tasks":
            lines.append(f"  🔍 Найти задачи: {args.get('search', 'все')}")
        elif name == "update_task_status":
            lines.append(
                f"  🔄 Статус «{args.get('search', '?')}» → "
                f"{STATUS_LABEL.get(args.get('status', ''), args.get('status', '?'))}"
            )
        elif name == "update_task_priority":
            p = args.get("priority", "?")
            lines.append(
                f"  🎯 Приоритет «{args.get('search', '?')}» → "
                f"{PRIORITY_EMOJI.get(p, '🔵')} {PRIORITY_LABEL.get(p, p)}"
            )
        elif name == "assign_task":
            lines.append(
                f"  👤 Назначить «{args.get('search', '?')}» → @{args.get('assignee_username', '?')}"
            )

        elif name == "update_task_description":
            lines.append(
                f"  📝 Описание «{args.get('search', '?')}» → "
                f"{args.get('description', '?')[:50]}…"
            )

    await state.set_state(VoiceConfirm.waiting)
    await state.update_data(
        tool_calls=tool_calls, user_id=user_id, transcript=transcript
    )

    await status_msg.edit_text(
        "\n".join(lines),
        reply_markup=_kb_confirm(uid),
        parse_mode="HTML",
    )


# ── Подтверждение ─────────────────────────────────────────────────────────────


@router.callback_query(VoiceConfirm.waiting, F.data.startswith("vc:ok:"))
async def confirm_execute(callback: CallbackQuery, state: FSMContext):
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    data = await state.get_data()
    tool_calls: list[dict] = data["tool_calls"]
    user_id: int = data["user_id"]

    results = []
    try:
        async with UnitOfWork(get_session_maker()) as uow:
            for tc in tool_calls:
                result = await _execute_tool(
                    tc["name"], tc["arguments"], user_id, uow.session
                )
                results.append(result)
            await uow.commit()
    except Exception as e:
        logger.exception("Tool execution error: %s", e)
        await callback.message.edit_text("❌ Ошибка при выполнении команды.")
        await callback.answer()
        await state.clear()
        return

    await state.clear()

    response_text = "\n\n".join(results)
    await callback.message.edit_text(response_text, parse_mode="HTML")
    await callback.answer()

    # Сохраняем результат в память
    await add_message(user_id, "assistant", response_text)


# ── Отмена ────────────────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("vc:no:"))
async def cancel_execute(callback: CallbackQuery, state: FSMContext):
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await state.clear()
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()
