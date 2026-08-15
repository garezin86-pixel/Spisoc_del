"""Тесты моста между общей Telegram-группой и общим каналом чата Spisoc.

Стиль — как в tests/test_bot.py: хендлеры вызываются напрямую (без реального
диспетчера aiogram), зависимости мокаются через MagicMock/AsyncMock.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.handlers import chat_bridge
from src.bot.middlewares.auth import AuthMiddleware
from src.services import chat_service


def make_tg_message(*, text="привет из телеграма", tg_id=123456789, is_bot=False, chat_id=999):
    msg = AsyncMock()
    msg.text = text
    msg.from_user = MagicMock()
    msg.from_user.id = tg_id
    msg.from_user.is_bot = is_bot
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    return msg


def make_user(*, id=1, username="alice", is_active=True):
    u = MagicMock()
    u.id = id
    u.username = username
    u.is_active = is_active
    u.groups = []
    return u


class TestChatBridgeIncoming:
    """Telegram → веб (src/bot/handlers/chat_bridge.py)."""

    @pytest.mark.asyncio
    async def test_registered_user_message_creates_chat_message(self):
        message = make_tg_message()
        user = make_user()

        with (
            patch("src.bot.handlers.chat_bridge.CHAT_BRIDGE_GROUP_ID", 999),
            patch("src.bot.handlers.chat_bridge.get_session_maker"),
            patch("src.bot.handlers.chat_bridge.UnitOfWork") as MockUow,
            patch("src.bot.handlers.chat_bridge.ChatRepository"),
            patch.object(chat_bridge, "ChatService") as MockService,
        ):
            uow_instance = AsyncMock()
            uow_instance.__aenter__ = AsyncMock(return_value=uow_instance)
            uow_instance.__aexit__ = AsyncMock(return_value=False)
            uow_instance.users = AsyncMock()
            uow_instance.users.get_by_telegram_id = AsyncMock(return_value=user)
            uow_instance.session = MagicMock()
            MockUow.return_value = uow_instance

            service_instance = MockService.return_value
            service_instance.send_message = AsyncMock()

            await chat_bridge.handle_bridge_group_message(message)

            service_instance.send_message.assert_awaited_once_with(user, message.text, group_id=None, origin="telegram")

    @pytest.mark.asyncio
    async def test_unregistered_sender_is_silently_ignored(self):
        message = make_tg_message()

        with (
            patch("src.bot.handlers.chat_bridge.CHAT_BRIDGE_GROUP_ID", 999),
            patch("src.bot.handlers.chat_bridge.get_session_maker"),
            patch("src.bot.handlers.chat_bridge.UnitOfWork") as MockUow,
            patch.object(chat_bridge, "ChatService") as MockService,
        ):
            uow_instance = AsyncMock()
            uow_instance.__aenter__ = AsyncMock(return_value=uow_instance)
            uow_instance.__aexit__ = AsyncMock(return_value=False)
            uow_instance.users = AsyncMock()
            uow_instance.users.get_by_telegram_id = AsyncMock(return_value=None)
            MockUow.return_value = uow_instance

            await chat_bridge.handle_bridge_group_message(message)

            MockService.return_value.send_message.assert_not_called()
            message.answer.assert_not_called()  # молчим, не спамим группу

    @pytest.mark.asyncio
    async def test_inactive_user_is_ignored(self):
        message = make_tg_message()
        user = make_user(is_active=False)

        with (
            patch("src.bot.handlers.chat_bridge.CHAT_BRIDGE_GROUP_ID", 999),
            patch("src.bot.handlers.chat_bridge.get_session_maker"),
            patch("src.bot.handlers.chat_bridge.UnitOfWork") as MockUow,
            patch.object(chat_bridge, "ChatService") as MockService,
        ):
            uow_instance = AsyncMock()
            uow_instance.__aenter__ = AsyncMock(return_value=uow_instance)
            uow_instance.__aexit__ = AsyncMock(return_value=False)
            uow_instance.users = AsyncMock()
            uow_instance.users.get_by_telegram_id = AsyncMock(return_value=user)
            MockUow.return_value = uow_instance

            await chat_bridge.handle_bridge_group_message(message)

            MockService.return_value.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_own_message_ignored_to_prevent_loop(self):
        message = make_tg_message(is_bot=True)

        with (
            patch("src.bot.handlers.chat_bridge.CHAT_BRIDGE_GROUP_ID", 999),
            patch.object(chat_bridge, "ChatService") as MockService,
        ):
            await chat_bridge.handle_bridge_group_message(message)
            MockService.assert_not_called()

    @pytest.mark.asyncio
    async def test_command_message_ignored(self):
        message = make_tg_message(text="/help")

        with (
            patch("src.bot.handlers.chat_bridge.CHAT_BRIDGE_GROUP_ID", 999),
            patch.object(chat_bridge, "ChatService") as MockService,
        ):
            await chat_bridge.handle_bridge_group_message(message)
            MockService.assert_not_called()

    @pytest.mark.asyncio
    async def test_bridge_disabled_does_nothing(self):
        message = make_tg_message()
        with (
            patch("src.bot.handlers.chat_bridge.CHAT_BRIDGE_GROUP_ID", 0),
            patch.object(chat_bridge, "ChatService") as MockService,
        ):
            await chat_bridge.handle_bridge_group_message(message)
            MockService.assert_not_called()


class TestChatServiceOutgoingMirror:
    """Веб → Telegram (ChatService._mirror_to_telegram)."""

    @pytest.mark.asyncio
    async def test_web_origin_general_channel_mirrors_to_telegram(self):
        repo = AsyncMock()
        repo.create = AsyncMock(return_value=MagicMock(id=1, content="привет", group_id=None, user=None))
        service = chat_service.ChatService(repo)
        user = make_user()

        with (
            patch("src.services.chat_service.CHAT_BRIDGE_GROUP_ID", 999),
            patch("src.services.chat_service.get_bot") as mock_get_bot,
            patch("src.services.chat_service.ws_manager") as mock_ws,
        ):
            mock_ws.broadcast_all = AsyncMock()
            bot = AsyncMock()
            mock_get_bot.return_value = bot

            await service.send_message(user, "привет", group_id=None, origin="web")

            bot.send_message.assert_awaited_once()
            assert bot.send_message.call_args.kwargs["chat_id"] == 999

    @pytest.mark.asyncio
    async def test_telegram_origin_does_not_mirror_back(self):
        """Сообщение, пришедшее ИЗ Telegram, не должно улетать обратно — иначе цикл."""
        repo = AsyncMock()
        repo.create = AsyncMock(return_value=MagicMock(id=1, content="привет", group_id=None, user=None))
        service = chat_service.ChatService(repo)
        user = make_user()

        with (
            patch("src.services.chat_service.CHAT_BRIDGE_GROUP_ID", 999),
            patch("src.services.chat_service.get_bot") as mock_get_bot,
            patch("src.services.chat_service.ws_manager") as mock_ws,
        ):
            mock_ws.broadcast_all = AsyncMock()

            await service.send_message(user, "привет", group_id=None, origin="telegram")

            mock_get_bot.assert_not_called()

    @pytest.mark.asyncio
    async def test_group_channel_never_mirrors(self):
        repo = AsyncMock()
        repo.create = AsyncMock(return_value=MagicMock(id=1, content="привет", group_id=5, user=None))
        repo.get_group_member_ids = AsyncMock(return_value=[1, 2])
        service = chat_service.ChatService(repo)
        user = make_user()
        user.groups = [MagicMock(id=5)]

        with (
            patch("src.services.chat_service.CHAT_BRIDGE_GROUP_ID", 999),
            patch("src.services.chat_service.get_bot") as mock_get_bot,
            patch("src.services.chat_service.ws_manager") as mock_ws,
        ):
            mock_ws.broadcast_to_users = AsyncMock()

            await service.send_message(user, "привет", group_id=5, origin="web")

            mock_get_bot.assert_not_called()

    @pytest.mark.asyncio
    async def test_bridge_disabled_no_mirror_attempt(self):
        repo = AsyncMock()
        repo.create = AsyncMock(return_value=MagicMock(id=1, content="привет", group_id=None, user=None))
        service = chat_service.ChatService(repo)
        user = make_user()

        with (
            patch("src.services.chat_service.CHAT_BRIDGE_GROUP_ID", 0),
            patch("src.services.chat_service.get_bot") as mock_get_bot,
            patch("src.services.chat_service.ws_manager") as mock_ws,
        ):
            mock_ws.broadcast_all = AsyncMock()

            await service.send_message(user, "привет", group_id=None, origin="web")

            mock_get_bot.assert_not_called()

    @pytest.mark.asyncio
    async def test_mirror_failure_does_not_raise(self):
        """Сбой отправки в Telegram не должен ронять основной путь (сообщение уже сохранено в веб-чате)."""
        repo = AsyncMock()
        repo.create = AsyncMock(return_value=MagicMock(id=1, content="привет", group_id=None, user=None))
        service = chat_service.ChatService(repo)
        user = make_user()

        with (
            patch("src.services.chat_service.CHAT_BRIDGE_GROUP_ID", 999),
            patch("src.services.chat_service.get_bot") as mock_get_bot,
            patch("src.services.chat_service.ws_manager") as mock_ws,
        ):
            mock_ws.broadcast_all = AsyncMock()
            bot = AsyncMock()
            bot.send_message = AsyncMock(side_effect=Exception("Telegram API down"))
            mock_get_bot.return_value = bot

            result = await service.send_message(user, "привет", group_id=None, origin="web")

            assert result is not None  # не упало


class TestAuthMiddlewareBridgeExemption:
    @pytest.mark.asyncio
    async def test_bridge_group_message_skips_strict_auth(self):
        from unittest.mock import create_autospec

        from aiogram.types import Message as AiogramMessage

        message = create_autospec(AiogramMessage, instance=True)
        message.chat = MagicMock()
        message.chat.id = 999
        message.text = "любой текст"
        message.answer = AsyncMock()

        middleware = AuthMiddleware()
        handler = AsyncMock(return_value="ok")

        with patch("src.bot.middlewares.auth.CHAT_BRIDGE_GROUP_ID", 999):
            result = await middleware(handler, message, {"state": MagicMock()})

        assert result == "ok"
        handler.assert_awaited_once()
        message.answer.assert_not_called()  # никакого "нет доступа" в группу

    @pytest.mark.asyncio
    async def test_chatid_command_skips_strict_auth_for_unregistered_sender(self):
        """Иначе узнать chat_id новой, ещё не привязанной группы будет неоткуда."""
        from unittest.mock import create_autospec

        from aiogram.types import Message as AiogramMessage

        message = create_autospec(AiogramMessage, instance=True)
        message.chat = MagicMock()
        message.chat.id = -1009999999  # незнакомый, ещё не настроенный чат
        message.text = "/chatid"
        message.answer = AsyncMock()

        middleware = AuthMiddleware()
        handler = AsyncMock(return_value="ok")

        with patch("src.bot.middlewares.auth.CHAT_BRIDGE_GROUP_ID", 0):
            result = await middleware(handler, message, {"state": MagicMock()})

        assert result == "ok"
        handler.assert_awaited_once()


class TestChatIdCommand:
    @pytest.mark.asyncio
    async def test_replies_with_chat_id_and_type(self):
        from src.bot.handlers.commands import cmd_chatid

        message = AsyncMock()
        message.chat = MagicMock()
        message.chat.id = -1001234567890
        message.chat.type = "supergroup"
        message.answer = AsyncMock()

        await cmd_chatid(message)

        message.answer.assert_awaited_once()
        reply_text = message.answer.call_args.args[0]
        assert "-1001234567890" in reply_text
        assert "supergroup" in reply_text
