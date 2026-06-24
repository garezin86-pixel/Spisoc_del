"""
src/bot/handlers/voice.py

Обработчик голосовых сообщений:
1. Скачивает .ogg от Telegram
2. Транскрибирует через Groq Whisper
3. Парсит в задачу через Gemini
4. Показывает карточку подтверждения
5. При подтверждении создаёт задачу через TaskService
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

from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.models.task import TaskPriority, TaskStatus
from src.repositories.groups_repository import GroupRepository
from src.repositories.task_repository import TaskRepository
from src.repositories.users_repository import UserRepository
from src.services.task_service import TaskService
from src.services.voice_ai import process_voice_message

logger = logging.getLogger(__name__)

router = Router()

LOCAL_TZ = ZoneInfo("Europe/Kiev")

PRIORITY_EMOJI = {
    "low": "⚪",
    "medium": "🔵",
    "high": "🟠",
    "critical": "🔴",
}

PRIORITY_LABEL = {
    "low": "Низкий",
    "medium": "Средний",
    "high": "Высокий",
    "critical": "Критический",
}


class VoiceTask(StatesGroup):
    confirm = State()


def _make_task_service(uow: UnitOfWork) -> TaskService:
    return TaskService(
        task_repo=TaskRepository(uow.session),
        user_repo=UserRepository(uow.session),
        group_repo=GroupRepository(uow.session),
        session=uow.session,
    )


def _confirm_keyboard(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Создать", callback_data=f"voice:confirm:{uid}"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=f"voice:cancel:{uid}"
                ),
            ],
        ]
    )


def _format_preview(transcript: str, task: dict) -> str:
    priority = task.get("priority", "medium")
    deadline = task.get("deadline")
    description = task.get("description")

    lines = [
        "🎤 <b>Распознал:</b>",
        f"<i>{transcript}</i>",
        "",
        "📌 <b>Задача:</b>",
        f"  <b>Название:</b> {task['title']}",
    ]
    if description:
        lines.append(f"  <b>Описание:</b> {description}")
    lines.append(
        f"  <b>Приоритет:</b> {PRIORITY_EMOJI.get(priority, '🔵')} "
        f"{PRIORITY_LABEL.get(priority, priority)}"
    )
    if deadline:
        dl_time = task.get("deadline_time")
        dl_str = deadline
        if dl_time:
            dl_str = f"{deadline} в {dl_time}"
        lines.append(f"  <b>Дедлайн:</b> {dl_str}")
    lines += ["", "Создать задачу?"]
    return "\n".join(lines)


# ── Шаг 1: получаем голосовое ─────────────────────────────────────────────────


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

    try:
        voice = message.voice
        assert voice is not None
        file = await bot.get_file(voice.file_id)
        buf = io.BytesIO()
        if not file.file_path:
            raise ValueError("file_path is None")
        await bot.download_file(file.file_path, destination=buf)

        transcript, task_data = await process_voice_message(buf.getvalue())

    except Exception as e:
        logger.exception("Voice processing error: %s", e)
        await status_msg.edit_text(
            "❌ Не удалось обработать голосовое. Попробуйте ещё раз."
        )
        return

    await state.set_state(VoiceTask.confirm)
    await state.update_data(task_data=task_data, transcript=transcript, user_id=user_id)

    uid = str(message.from_user.id)
    await status_msg.edit_text(
        _format_preview(transcript, task_data),
        reply_markup=_confirm_keyboard(uid),
        parse_mode="HTML",
    )


# ── Шаг 2а: подтверждение ─────────────────────────────────────────────────────


@router.callback_query(VoiceTask.confirm, F.data.startswith("voice:confirm:"))
async def confirm_voice_task(callback: CallbackQuery, state: FSMContext):
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
                deadline_time = task_data.get("deadline_time")
                if deadline_time:
                    try:
                        t = datetime.strptime(deadline_time, "%H:%M")
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
            from src.models.task import SpisokModel

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
        if task_data.get("deadline"):
            dl_time = task_data.get("deadline_time")
            dl = f"\n📅 {task_data['deadline']}" + (f" в {dl_time}" if dl_time else "")
        else:
            dl = ""
        await callback.message.edit_text(
            f"✅ <b>Задача создана!</b>\n\n"
            f"📌 {task.title}\n"
            f"{emoji} {PRIORITY_LABEL.get(priority.value, priority.value)}{dl}",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.exception("Failed to create task from voice: %s", e)
        await callback.message.edit_text("❌ Ошибка при создании задачи.")
    finally:
        await callback.answer()


# ── Шаг 2б: отмена ────────────────────────────────────────────────────────────


@router.callback_query(VoiceTask.confirm, F.data.startswith("voice:cancel:"))
async def cancel_voice_task(callback: CallbackQuery, state: FSMContext):
    if not isinstance(callback.message, Message):
        await callback.answer()
        return
    await state.clear()
    await callback.message.edit_text("❌ Создание задачи отменено.")
    await callback.answer()
