# tests/test_voice_handler_rate_limit.py
"""
Тесты для src/bot/handlers/voice.py — конкретно интеграция с rate-limit'ом.

Главное, что здесь проверяется: при превышении лимита process_voice_message
(а значит и Groq — Whisper + LLaMA) НЕ вызывается вообще. Именно в этом
смысл лимита — не просто вернуть пользователю отказ, а не потратить деньги
на Groq ДО того, как отказ принят.

UnitOfWork мокается целиком (реальная БД не поднимается) — цель теста не
проверить репозитории, а проверить порядок операций в самом обработчике.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.bot.handlers.voice import handle_voice

pytestmark = pytest.mark.asyncio


def make_message():
    message = AsyncMock()
    message.from_user = SimpleNamespace(id=555)
    message.voice = SimpleNamespace(file_id="fake-file-id")
    message.answer = AsyncMock(return_value=AsyncMock())
    return message


def make_uow_context(user):
    """Мок async-контекстного менеджера UnitOfWork с .users.get_by_telegram_id."""
    uow = AsyncMock()
    uow.users.get_by_telegram_id = AsyncMock(return_value=user)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=uow)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestHandleVoiceRateLimit:
    async def test_rate_limited_user_never_reaches_groq(self):
        """Главный тест: process_voice_message не должен вызываться, если
        лимит превышен — иначе rate limit не защищает от расходов."""
        fake_user = SimpleNamespace(id=11)

        with (
            patch("src.bot.handlers.voice.UnitOfWork", return_value=make_uow_context(fake_user)),
            patch(
                "src.bot.handlers.voice.check_voice_rate_limit",
                new_callable=AsyncMock,
                return_value=(False, 120),
            ),
            patch("src.bot.handlers.voice.process_voice_message", new_callable=AsyncMock) as mock_process,
        ):
            message = make_message()
            state = AsyncMock()
            bot = AsyncMock()

            await handle_voice(message, state, bot)

        mock_process.assert_not_called()
        bot.get_file.assert_not_called()  # даже файл голосового не скачивался

    async def test_rate_limited_user_sees_friendly_message(self):
        fake_user = SimpleNamespace(id=11)

        with (
            patch("src.bot.handlers.voice.UnitOfWork", return_value=make_uow_context(fake_user)),
            patch(
                "src.bot.handlers.voice.check_voice_rate_limit",
                new_callable=AsyncMock,
                return_value=(False, 120),
            ),
            patch("src.bot.handlers.voice.process_voice_message", new_callable=AsyncMock),
        ):
            message = make_message()
            await handle_voice(message, AsyncMock(), AsyncMock())

        last_call_text = message.answer.call_args.args[0]
        assert "⏳" in last_call_text
        assert "2 мин" in last_call_text  # 120 секунд -> округляется до 2 минут

    async def test_allowed_user_proceeds_to_groq(self):
        """Обратный случай: если лимит не превышен, обработка идёт как обычно."""
        fake_user = SimpleNamespace(id=11)

        with (
            patch("src.bot.handlers.voice.UnitOfWork", return_value=make_uow_context(fake_user)),
            patch(
                "src.bot.handlers.voice.check_voice_rate_limit",
                new_callable=AsyncMock,
                return_value=(True, 0),
            ),
            patch(
                "src.bot.handlers.voice.process_voice_message",
                new_callable=AsyncMock,
                return_value=("текст", [{"name": "text_response", "arguments": {"text": "ok"}}]),
            ) as mock_process,
            patch("src.bot.handlers.voice.get_history", new_callable=AsyncMock, return_value=[]),
            patch("src.bot.handlers.voice.add_message", new_callable=AsyncMock),
        ):
            message = make_message()
            bot = AsyncMock()
            bot.get_file = AsyncMock(return_value=SimpleNamespace(file_path="voice.ogg"))
            bot.download_file = AsyncMock()

            await handle_voice(message, AsyncMock(), bot)

        mock_process.assert_called_once()

    async def test_unregistered_user_never_checked_against_rate_limit(self):
        """Незарегистрированный пользователь отсеивается раньше проверки
        лимита — нет смысла тратить Redis-запрос на того, кто и так не
        дойдёт до Groq (см. проверку 'Сначала зарегистрируйтесь')."""
        with (
            patch("src.bot.handlers.voice.UnitOfWork", return_value=make_uow_context(None)),
            patch("src.bot.handlers.voice.check_voice_rate_limit", new_callable=AsyncMock) as mock_rate_limit,
        ):
            message = make_message()
            await handle_voice(message, AsyncMock(), AsyncMock())

        mock_rate_limit.assert_not_called()
