"""
src/bot/handlers/voice.py

Голосовой ввод: распознавание речи (Groq Whisper) → выбор инструментов (LLM) → тот же агент, что и для текста
(src/ai, см. ai_assistant.py): чтение выполняется сразу, запись — после «да», при нескольких подходящих записях — кнопки
выбора. Контекст диалога хранится в Redis (chat_memory).
"""

import io
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, Message

from src.ai import default_registry
from src.ai.llm import build_hints
from src.bot.handlers.ai_assistant import _esc, deliver, run_turn
from src.db import get_session_maker
from src.db.unit_of_work import UnitOfWork
from src.services.chat_memory import add_message, get_history
from src.services.voice_ai import process_voice_message
from src.services.voice_rate_limit import check_voice_rate_limit

logger = logging.getLogger(__name__)
router = Router()


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
        # Инструменты — только доступные этому пользователю по роли: LLM не видит и не может вызвать лишнее
        registry = default_registry()
        tools = registry.definitions(user)
        hints = build_hints(registry.hints(user))

    # Проверяем ДО скачивания файла и вызовов Groq — иначе rate limit не
    # защищает от расходов, которые уже случились к моменту проверки.
    allowed, retry_after = await check_voice_rate_limit(user_id)
    if not allowed:
        minutes = max(1, retry_after // 60)
        await message.answer(f"⏳ Слишком много голосовых команд подряд. Попробуйте снова через ~{minutes} мин.")
        return

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
        transcript, tool_calls = await process_voice_message(buf.getvalue(), history, tools=tools, extra_hints=hints)

    except Exception as e:
        logger.exception("Voice processing error: %s", e)
        await status_msg.edit_text("❌ Не удалось обработать голосовое. Попробуйте ещё раз.")
        return

    # Сохраняем запрос пользователя в память
    await add_message(user_id, "user", transcript)
    prefix = f"🎤 <i>{_esc(transcript)}</i>"

    # Только текстовый ответ модели (вопрос, непонятная команда) — без обращения к БД и подтверждений
    if all(tc["name"] == "text_response" for tc in tool_calls):
        resp = "\n".join(tc["arguments"].get("text", "") for tc in tool_calls).strip()
        await status_msg.edit_text(f"{prefix}\n\n{_esc(resp)}", parse_mode="HTML")
        await add_message(user_id, "assistant", resp)
        return

    try:
        turn = await run_turn(user_id, lambda agent, ctx: agent.run_calls(ctx, tool_calls))
    except Exception as e:
        logger.exception("Voice command execution error: %s", e)
        await status_msg.edit_text(f"{prefix}\n\n❌ Ошибка при выполнении команды.", parse_mode="HTML")
        return

    async def send(body: str, markup: InlineKeyboardMarkup | None) -> object:
        return await status_msg.edit_text(body, reply_markup=markup, parse_mode="HTML")

    await deliver(turn, state=state, user_id=user_id, send=send, prefix=prefix)
