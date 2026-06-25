"""
src/bot/handlers/voice.py

Поддерживаемые голосовые команды:
- создать задачу
- найти задачу
- изменить статус задачи
- изменить приоритет задачи
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


class VoiceTask(StatesGroup):
    confirm_create = State()
    confirm_status = State()
    confirm_priority = State()
    confirm_assign = State()


# ── Клавиатуры ────────────────────────────────────────────────────────────────


def _kb_create(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Создать", callback_data=f"voice:create:{uid}"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=f"voice:cancel:{uid}"
                ),
            ]
        ]
    )


def _kb_update(task_id: int, action: str, uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Применить", callback_data=f"voice:{action}:{task_id}:{uid}"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=f"voice:cancel:{uid}"
                ),
            ]
        ]
    )


# ── Превью задачи для создания ────────────────────────────────────────────────


def _format_create_preview(transcript: str, task: dict) -> str:
    priority = task.get("priority", "medium")
    deadline = task.get("deadline")
    deadline_time = task.get("deadline_time")
    description = task.get("description")

    lines = [
        "🎤 <b>Распознал:</b>",
        f"<i>{transcript}</i>",
        "",
        "📌 <b>Новая задача:</b>",
        f"  <b>Название:</b> {task['title']}",
    ]
    if description:
        lines.append(f"  <b>Описание:</b> {description}")
    lines.append(
        f"  <b>Приоритет:</b> {PRIORITY_EMOJI.get(priority, '🔵')} {PRIORITY_LABEL.get(priority, priority)}"
    )
    if deadline:
        dl_str = deadline + (f" в {deadline_time}" if deadline_time else "")
        lines.append(f"  <b>Дедлайн:</b> {dl_str}")
    lines += ["", "Создать задачу?"]
    return "\n".join(lines)


# ── Поиск задач по тексту ─────────────────────────────────────────────────────


async def _search_users(session, query: str) -> list[UserModel]:
    """Ищет пользователей по username (частичное совпадение)."""
    words = [w.strip() for w in query.split() if len(w.strip()) > 1]
    if not words:
        words = [query]
    conditions = [UserModel.username.ilike(f"%{w}%") for w in words]
    result = await session.execute(select(UserModel).where(or_(*conditions)).limit(5))
    return list(result.scalars().all())


async def _search_tasks(session, user_id: int, query: str) -> list[SpisokModel]:
    words = [w.strip() for w in query.split() if len(w.strip()) > 2]
    if not words:
        words = [query]

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


def _kb_assign(task_id: int, user_id: int, uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Назначить",
                    callback_data=f"voice:assign:{task_id}:{user_id}:{uid}",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=f"voice:cancel:{uid}"
                ),
            ]
        ]
    )


def _format_task_short(task: SpisokModel) -> str:
    status = task.status.value if task.status else "todo"
    priority = task.priority.value if task.priority else "medium"
    return (
        f"#{task.id} {PRIORITY_EMOJI.get(priority, '🔵')} {task.title} "
        f"— {STATUS_LABEL.get(status, status)}"
    )


# ── Главный обработчик голосовых ──────────────────────────────────────────────


@router.message(F.voice)
async def handle_voice(message: Message, state: FSMContext, bot: Bot):
    assert message.from_user is not None

    async with UnitOfWork(get_session_maker()) as uow:
        user = await uow.users.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ Сначала зарегистрируйтесь через /start")
            return
        user_id = user.id

    status_msg = await message.answer("🎤 Обрабатываю голосовое…")
    uid = str(message.from_user.id)

    try:
        voice = message.voice
        assert voice is not None
        file = await bot.get_file(voice.file_id)
        if not file.file_path:
            raise ValueError("file_path is None")
        buf = io.BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        transcript, intent_data = await process_voice_message(buf.getvalue())
    except Exception as e:
        logger.exception("Voice processing error: %s", e)
        await status_msg.edit_text(
            "❌ Не удалось обработать голосовое. Попробуйте ещё раз."
        )
        return

    intent = intent_data.get("intent", "create")

    # ── CREATE ────────────────────────────────────────────────────────────────
    if intent == "create":
        await state.set_state(VoiceTask.confirm_create)
        await state.update_data(
            task_data=intent_data, transcript=transcript, user_id=user_id
        )
        await status_msg.edit_text(
            _format_create_preview(transcript, intent_data),
            reply_markup=_kb_create(uid),
            parse_mode="HTML",
        )

    # ── FIND ──────────────────────────────────────────────────────────────────
    elif intent == "find":
        search_query = intent_data.get("search_query", transcript)
        async with UnitOfWork(get_session_maker()) as uow:
            tasks = await _search_tasks(uow.session, user_id, search_query)

        if not tasks:
            await status_msg.edit_text(
                f"🔍 По запросу «{search_query}» задачи не найдены."
            )
        else:
            lines = [f"🔍 <b>Найдено по «{search_query}»:</b>", ""]
            for t in tasks:
                lines.append(_format_task_short(t))
            await status_msg.edit_text("\n".join(lines), parse_mode="HTML")

    # ── UPDATE STATUS ─────────────────────────────────────────────────────────
    elif intent == "update_status":
        search_query = intent_data.get("search_query", transcript)
        new_status = intent_data.get("status", "done")

        async with UnitOfWork(get_session_maker()) as uow:
            tasks = await _search_tasks(uow.session, user_id, search_query)

        if not tasks:
            await status_msg.edit_text(f"🔍 Задача «{search_query}» не найдена.")
            return

        task = tasks[0]
        status_label = STATUS_LABEL.get(new_status, new_status)

        await state.set_state(VoiceTask.confirm_status)
        await state.update_data(
            task_id=task.id,
            new_status=new_status,
            transcript=transcript,
            user_id=user_id,
        )
        await status_msg.edit_text(
            f"🎤 <b>Распознал:</b>\n<i>{transcript}</i>\n\n"
            f"📌 <b>{task.title}</b>\n"
            f"Изменить статус на <b>{status_label}</b>?",
            reply_markup=_kb_update(task.id, "status", uid),
            parse_mode="HTML",
        )

    # ── UPDATE PRIORITY ───────────────────────────────────────────────────────
    elif intent == "update_priority":
        search_query = intent_data.get("search_query", transcript)
        new_priority = intent_data.get("priority", "high")

        async with UnitOfWork(get_session_maker()) as uow:
            tasks = await _search_tasks(uow.session, user_id, search_query)

        if not tasks:
            await status_msg.edit_text(f"🔍 Задача «{search_query}» не найдена.")
            return

        task = tasks[0]
        priority_label = f"{PRIORITY_EMOJI.get(new_priority, '🔵')} {PRIORITY_LABEL.get(new_priority, new_priority)}"

        await state.set_state(VoiceTask.confirm_priority)
        await state.update_data(
            task_id=task.id,
            new_priority=new_priority,
            transcript=transcript,
            user_id=user_id,
        )
        await status_msg.edit_text(
            f"🎤 <b>Распознал:</b>\n<i>{transcript}</i>\n\n"
            f"📌 <b>{task.title}</b>\n"
            f"Изменить приоритет на <b>{priority_label}</b>?",
            reply_markup=_kb_update(task.id, "priority", uid),
            parse_mode="HTML",
        )

    # ── ASSIGN ───────────────────────────────────────────────────────────────
    elif intent == "assign":
        search_query = intent_data.get("search_query", transcript)
        assignee_query = intent_data.get("assignee", "")

        async with UnitOfWork(get_session_maker()) as uow:
            tasks = await _search_tasks(uow.session, user_id, search_query)
            users = (
                await _search_users(uow.session, assignee_query)
                if assignee_query
                else []
            )

        if not tasks:
            await status_msg.edit_text(f"🔍 Задача «{search_query}» не найдена.")
            return

        if not users:
            await status_msg.edit_text(
                f"🔍 Пользователь «{assignee_query}» не найден."
                f"Проверьте username и попробуйте снова."
            )
            return

        task = tasks[0]
        assignee = users[0]

        await state.set_state(VoiceTask.confirm_assign)
        await state.update_data(
            task_id=task.id,
            assignee_id=assignee.id,
            transcript=transcript,
            user_id=user_id,
        )
        await status_msg.edit_text(
            f"🎤 <b>Распознал:</b>\n<i>{transcript}</i>\n\n"
            f"📌 <b>{task.title}</b>\n"
            f"Назначить исполнителем: <b>@{assignee.username}</b>?",
            reply_markup=_kb_assign(task.id, assignee.id, uid),
            parse_mode="HTML",
        )

    else:
        await status_msg.edit_text("❓ Не понял команду. Попробуйте иначе.")


# ── Подтверждение: создать задачу ─────────────────────────────────────────────


@router.callback_query(VoiceTask.confirm_create, F.data.startswith("voice:create:"))
async def confirm_create(callback: CallbackQuery, state: FSMContext):
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    data = await state.get_data()
    task_data: dict = data["task_data"]
    user_id: int = data["user_id"]

    try:
        priority_val = task_data.get("priority", "medium")
        try:
            priority = TaskPriority(priority_val)
        except ValueError:
            priority = TaskPriority.medium

        deadline = None
        if task_data.get("deadline"):
            try:
                dl_time = task_data.get("deadline_time")
                if dl_time:
                    try:
                        t = datetime.strptime(dl_time, "%H:%M")
                        h, m = t.hour, t.minute
                    except ValueError:
                        h, m = 23, 59
                else:
                    h, m = 23, 59
                deadline = datetime.strptime(task_data["deadline"], "%Y-%m-%d").replace(
                    hour=h, minute=m, tzinfo=LOCAL_TZ
                )
            except ValueError:
                deadline = None

        async with UnitOfWork(get_session_maker()) as uow:
            uow.session.info["audit_user_id"] = user_id
            task = SpisokModel(
                title=task_data["title"],
                description=task_data.get("description"),
                priority=priority,
                status=TaskStatus.todo,
                deadline=deadline,
                user_id=user_id,
                author_id=user_id,
                group_id=None,
            )
            uow.session.add(task)
            await uow.session.flush()
            await uow.commit()
            await uow.session.refresh(task)

        await state.clear()
        emoji = PRIORITY_EMOJI.get(priority.value, "🔵")
        dl_str = ""
        if task_data.get("deadline"):
            dl_str = f"\n📅 {task_data['deadline']}"
            if task_data.get("deadline_time"):
                dl_str += f" в {task_data['deadline_time']}"

        await callback.message.edit_text(
            f"✅ <b>Задача создана!</b>\n\n"
            f"📌 {task.title}\n"
            f"{emoji} {PRIORITY_LABEL.get(priority.value, priority.value)}{dl_str}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Failed to create task: %s", e)
        await callback.message.edit_text("❌ Ошибка при создании задачи.")
    finally:
        await callback.answer()


# ── Подтверждение: изменить статус ────────────────────────────────────────────


@router.callback_query(VoiceTask.confirm_status, F.data.startswith("voice:status:"))
async def confirm_status(callback: CallbackQuery, state: FSMContext):
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    data = await state.get_data()
    task_id: int = data["task_id"]
    new_status: str = data["new_status"]

    try:
        async with UnitOfWork(get_session_maker()) as uow:
            uow.session.info["audit_user_id"] = data["user_id"]
            task = await uow.session.get(SpisokModel, task_id)
            if not task:
                await callback.message.edit_text("❌ Задача не найдена.")
                return
            task.status = TaskStatus(new_status)
            await uow.commit()

        await state.clear()
        status_label = STATUS_LABEL.get(new_status, new_status)
        await callback.message.edit_text(
            f"✅ <b>Статус обновлён!</b>\n\n" f"📌 {task.title}\n" f"→ {status_label}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Failed to update status: %s", e)
        await callback.message.edit_text("❌ Ошибка при обновлении статуса.")
    finally:
        await callback.answer()


# ── Подтверждение: изменить приоритет ─────────────────────────────────────────


@router.callback_query(VoiceTask.confirm_priority, F.data.startswith("voice:priority:"))
async def confirm_priority(callback: CallbackQuery, state: FSMContext):
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    data = await state.get_data()
    task_id: int = data["task_id"]
    new_priority: str = data["new_priority"]

    try:
        async with UnitOfWork(get_session_maker()) as uow:
            uow.session.info["audit_user_id"] = data["user_id"]
            task = await uow.session.get(SpisokModel, task_id)
            if not task:
                await callback.message.edit_text("❌ Задача не найдена.")
                return
            task.priority = TaskPriority(new_priority)
            await uow.commit()

        await state.clear()
        emoji = PRIORITY_EMOJI.get(new_priority, "🔵")
        label = PRIORITY_LABEL.get(new_priority, new_priority)
        await callback.message.edit_text(
            f"✅ <b>Приоритет обновлён!</b>\n\n"
            f"📌 {task.title}\n"
            f"→ {emoji} {label}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Failed to update priority: %s", e)
        await callback.message.edit_text("❌ Ошибка при обновлении приоритета.")
    finally:
        await callback.answer()


# ── Подтверждение: назначить исполнителя ─────────────────────────────────────


@router.callback_query(VoiceTask.confirm_assign, F.data.startswith("voice:assign:"))
async def confirm_assign(callback: CallbackQuery, state: FSMContext):
    if not isinstance(callback.message, Message):
        await callback.answer()
        return

    data = await state.get_data()
    task_id: int = data["task_id"]
    assignee_id: int = data["assignee_id"]

    try:
        async with UnitOfWork(get_session_maker()) as uow:
            uow.session.info["audit_user_id"] = data["user_id"]
            task = await uow.session.get(SpisokModel, task_id)
            assignee = await uow.session.get(UserModel, assignee_id)
            if not task or not assignee:
                await callback.message.edit_text(
                    "❌ Задача или пользователь не найдены."
                )
                return
            task.user_id = assignee_id
            await uow.commit()

        await state.clear()
        await callback.message.edit_text(
            f"✅ <b>Исполнитель назначен!</b>\n\n"
            f"📌 {task.title}\n"
            f"👤 @{assignee.username}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Failed to assign task: %s", e)
        await callback.message.edit_text("❌ Ошибка при назначении.")
    finally:
        await callback.answer()


# ── Отмена (любое состояние) ──────────────────────────────────────────────────


@router.callback_query(F.data.startswith("voice:cancel:"))
async def cancel_voice(callback: CallbackQuery, state: FSMContext):
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await state.clear()
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()
