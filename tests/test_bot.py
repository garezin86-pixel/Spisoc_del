"""
Тесты для Telegram-бота (aiogram).

Охват:
  - AuthMiddleware          (middlewares/auth.py)
  - cmd_start / deeplink    (handlers/start.py)
  - registration flow       (handlers/registration.py)
  - commands level 1-4      (handlers/commands.py)
  - trash handlers          (handlers/trash.py)  — входная точка

Все тесты — unit, без реального БД и без реального Telegram.
Используем MagicMock / AsyncMock для message, UnitOfWork, репозиториев.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# Вспомогательные фабрики
# ═══════════════════════════════════════════════════════════════════════════════


def make_user(
    *,
    id: int = 1,
    username: str = "testuser",
    role: str = "user",
    is_active: bool = True,
    telegram_id: int = 123456789,
):
    """Создаёт мок-пользователя."""
    u = MagicMock()
    u.id = id
    u.username = username
    u.role = role
    u.is_active = is_active
    u.telegram_id = telegram_id
    return u


def make_task(
    *,
    id: int = 42,
    title: str = "Test task",
    description: str = "desc",
    status_value: str = "todo",
    priority_value: str = "medium",
    deadline=None,
    author_username: str = "author",
    deleted_at=None,
):
    """Создаёт мок-задачу."""
    t = MagicMock()
    t.id = id
    t.title = title
    t.description = description
    t.deadline = deadline
    t.deleted_at = deleted_at
    t.status = MagicMock()
    t.status.value = status_value
    t.priority = MagicMock()
    t.priority.value = priority_value
    t.author = MagicMock()
    t.author.username = author_username
    return t


def make_message(
    *,
    text: str = "/start",
    tg_id: int = 123456789,
    username: str = "tg_user",
    reply_markup=None,
    chat_id: int = 999999999,
    as_aiogram_type: bool = False,
):
    """
    Создаёт мок aiogram Message.

    as_aiogram_type=True — использует create_autospec(Message) чтобы
    isinstance(msg, Message) возвращал True (нужно для middleware).

    chat_id — id чата сообщения (AuthMiddleware проверяет event.chat.id для
    моста с группой, см. src/bot/middlewares/auth.py). Дефолт — просто
    заведомо непохожее на реальный Telegram group id число; тесты моста
    всё равно должны явно патчить CHAT_BRIDGE_GROUP_ID, а не полагаться на
    то, что chat_id с ним случайно не совпадёт (иначе поведение тестов
    будет зависеть от значения в локальном .env, как и было до этого фикса).
    """
    if as_aiogram_type:
        from unittest.mock import create_autospec as _cas

        from aiogram.types import Message as AiogramMessage

        msg = _cas(AiogramMessage, instance=True)
        msg.text = text
        msg.from_user = MagicMock()
        msg.from_user.id = tg_id
        msg.from_user.username = username
        msg.answer = AsyncMock()
        msg.chat = MagicMock()
        msg.chat.id = chat_id
    else:
        msg = AsyncMock()
        msg.text = text
        msg.from_user = MagicMock()
        msg.from_user.id = tg_id
        msg.from_user.username = username
        msg.answer = AsyncMock()
        msg.chat = MagicMock()
        msg.chat.id = chat_id
    return msg


def make_command_object(args: str | None):
    """Мок CommandObject."""
    cmd = MagicMock()
    cmd.args = args
    return cmd


def make_uow(user=None, tasks=None, group=None):
    """
    Создаёт AsyncMock UnitOfWork с нужными репозиториями.
    Используется как async context manager.
    """
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)

    # users repo
    uow.users = AsyncMock()
    uow.users.get_by_telegram_id = AsyncMock(return_value=user)
    uow.users.get_by_username = AsyncMock(return_value=None)
    uow.users.get_by_login = AsyncMock(return_value=None)

    # tasks repo
    uow.tasks = AsyncMock()
    uow.tasks.create = AsyncMock(return_value=make_task())

    # groups
    uow.groups = AsyncMock()
    uow.groups.get_by_id = AsyncMock(return_value=group)

    uow.session = MagicMock()
    uow.session.info = {}
    uow.set_audit_user = MagicMock()
    uow.commit = AsyncMock()

    return uow


# ═══════════════════════════════════════════════════════════════════════════════
# AuthMiddleware
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuthMiddleware:
    """Тесты для middlewares/auth.py."""

    @pytest.fixture
    def middleware(self):
        from src.bot.middlewares.auth import AuthMiddleware

        return AuthMiddleware()

    @pytest.mark.asyncio
    async def test_passes_start_command(self, middleware):
        """Сообщение /start должно пройти мимо проверки авторизации."""

        handler = AsyncMock(return_value="ok")
        message = make_message(text="/start", as_aiogram_type=True)
        data = {"state": MagicMock()}

        with patch("src.bot.middlewares.auth.CHAT_BRIDGE_GROUP_ID", 0):
            result = await middleware(handler, message, data)

        assert result == "ok"
        handler.assert_called_once_with(message, data)

    @pytest.mark.asyncio
    async def test_passes_application_button(self, middleware):
        """Кнопка «Подать заявку» должна пройти без проверки."""
        handler = AsyncMock(return_value="ok")
        message = make_message(text="📝 Подать заявку")
        data = {"state": MagicMock()}

        await middleware(handler, message, data)
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_registration_fsm_state(self, middleware):
        """В состоянии Registration.* должен пропускать без проверки."""
        handler = AsyncMock(return_value="ok")
        message = make_message(text="Иванов Иван Иванович")
        fsm = AsyncMock()
        fsm.get_state = AsyncMock(return_value="Registration:waiting_for_fio")
        data = {"state": fsm}

        await middleware(handler, message, data)
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_blocks_unknown_user(self, middleware):
        """Незарегистрированный пользователь должен получить отказ."""
        from unittest.mock import create_autospec

        from aiogram.fsm.context import FSMContext

        handler = AsyncMock()
        message = make_message(text="/my", as_aiogram_type=True)
        fsm = create_autospec(FSMContext, instance=True)
        fsm.get_state = AsyncMock(return_value=None)
        data = {"state": fsm}

        uow = make_uow(user=None)

        with (
            patch("src.bot.middlewares.auth.UnitOfWork", return_value=uow),
            patch("src.bot.middlewares.auth.get_session_maker"),
            patch("src.bot.middlewares.auth.CHAT_BRIDGE_GROUP_ID", 0),
        ):
            await middleware(handler, message, data)

        message.answer.assert_called_once()
        assert "доступ" in message.answer.call_args[0][0]
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_blocks_inactive_user(self, middleware):
        """Заблокированный пользователь должен получить отказ."""
        from unittest.mock import create_autospec

        from aiogram.fsm.context import FSMContext

        handler = AsyncMock()
        message = make_message(text="/my", as_aiogram_type=True)
        fsm = create_autospec(FSMContext, instance=True)
        fsm.get_state = AsyncMock(return_value=None)
        data = {"state": fsm}

        user = make_user(is_active=False)
        uow = make_uow(user=user)

        with (
            patch("src.bot.middlewares.auth.UnitOfWork", return_value=uow),
            patch("src.bot.middlewares.auth.get_session_maker"),
            patch("src.bot.middlewares.auth.CHAT_BRIDGE_GROUP_ID", 0),
        ):
            await middleware(handler, message, data)

        message.answer.assert_called_once()
        assert "заблокирован" in message.answer.call_args[0][0]
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_passes_active_registered_user(self, middleware):
        """Активный зарегистрированный пользователь должен пройти."""
        from unittest.mock import create_autospec

        from aiogram.fsm.context import FSMContext

        handler = AsyncMock(return_value="ok")
        message = make_message(text="/my", as_aiogram_type=True)
        fsm = create_autospec(FSMContext, instance=True)
        fsm.get_state = AsyncMock(return_value=None)
        data = {"state": fsm}

        user = make_user(is_active=True)
        uow = make_uow(user=user)

        with (
            patch("src.bot.middlewares.auth.UnitOfWork", return_value=uow),
            patch("src.bot.middlewares.auth.get_session_maker"),
            patch("src.bot.middlewares.auth.CHAT_BRIDGE_GROUP_ID", 0),
        ):
            await middleware(handler, message, data)

        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_bridge_group_message_skips_auth_check(self, middleware):
        """Сообщение из привязанной Telegram-группы (мост) должно пройти к
        хендлеру напрямую, минуя проверку регистрации/блокировки — даже для
        незарегистрированного пользователя. Раньше эта ветка вообще не была
        покрыта тестами."""
        bridge_group_id = -100123456789
        handler = AsyncMock(return_value="ok")
        message = make_message(text="привет всем", chat_id=bridge_group_id, as_aiogram_type=True)
        data = {"state": MagicMock()}

        with patch("src.bot.middlewares.auth.CHAT_BRIDGE_GROUP_ID", bridge_group_id):
            result = await middleware(handler, message, data)

        assert result == "ok"
        handler.assert_called_once_with(message, data)

    @pytest.mark.asyncio
    async def test_non_bridge_group_message_is_still_checked(self, middleware):
        """Сообщение из ДРУГОЙ группы (не привязанной как мост) не должно
        обходить проверку регистрации — иначе любая группа стала бы дырой."""
        from unittest.mock import create_autospec

        from aiogram.fsm.context import FSMContext

        handler = AsyncMock()
        message = make_message(text="/my", chat_id=-100999999999, as_aiogram_type=True)
        fsm = create_autospec(FSMContext, instance=True)
        fsm.get_state = AsyncMock(return_value=None)
        data = {"state": fsm}

        uow = make_uow(user=None)

        with (
            patch("src.bot.middlewares.auth.UnitOfWork", return_value=uow),
            patch("src.bot.middlewares.auth.get_session_maker"),
            patch("src.bot.middlewares.auth.CHAT_BRIDGE_GROUP_ID", -100123456789),  # другой id, не совпадает
        ):
            await middleware(handler, message, data)

        handler.assert_not_called()
        message.answer.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# handlers/start.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestCmdStart:
    """Тесты для обычного /start."""

    @pytest.mark.asyncio
    async def test_start_unknown_user_shows_registration_button(self):
        from src.bot.handlers.start import cmd_start

        message = make_message()
        uow = make_uow(user=None)

        with (
            patch("src.bot.handlers.start.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.start.get_session_maker"),
        ):
            await cmd_start(message)

        message.answer.assert_called_once()
        call_kwargs = message.answer.call_args
        # Проверяем reply_markup передан (кнопка заявки)
        assert call_kwargs.kwargs.get("reply_markup") is not None or len(call_kwargs.args) > 0

    @pytest.mark.asyncio
    async def test_start_inactive_user_blocked(self):
        from src.bot.handlers.start import cmd_start

        message = make_message()
        user = make_user(is_active=False)
        uow = make_uow(user=user)

        with (
            patch("src.bot.handlers.start.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.start.get_session_maker"),
        ):
            await cmd_start(message)

        message.answer.assert_called_once()
        assert "заблокирован" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_start_user_gets_user_menu(self):
        from src.bot.handlers.start import cmd_start

        message = make_message()
        user = make_user(role="user")
        uow = make_uow(user=user)

        with (
            patch("src.bot.handlers.start.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.start.get_session_maker"),
            patch("src.bot.handlers.start.main_menu_user_keyboard") as mock_kb,
        ):
            mock_kb.return_value = MagicMock()
            await cmd_start(message)

        mock_kb.assert_called_once()
        message.answer.assert_called_once()
        assert "testuser" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_start_admin_gets_admin_menu(self):
        from src.bot.handlers.start import cmd_start

        message = make_message()
        user = make_user(role="admin")
        uow = make_uow(user=user)

        with (
            patch("src.bot.handlers.start.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.start.get_session_maker"),
            patch("src.bot.handlers.start.main_menu_admin_keyboard") as mock_kb,
        ):
            mock_kb.return_value = MagicMock()
            await cmd_start(message)

        mock_kb.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# handlers/registration.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegistration:
    """Тесты для flow регистрации."""

    @pytest.mark.asyncio
    async def test_registration_start_sets_state(self):
        from src.bot.handlers.registration import registration_start

        message = make_message(text="📝 Подать заявку")
        state = AsyncMock()

        await registration_start(message, state)

        state.set_state.assert_called_once()
        message.answer.assert_called_once()
        assert "ФИО" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_registration_fio_too_short(self):
        from src.bot.handlers.registration import registration_fio

        message = make_message(text="Ив")
        state = AsyncMock()

        await registration_fio(message, state)

        message.answer.assert_called_once()
        assert "ФИО" in message.answer.call_args[0][0]
        # State не должен очищаться при ошибке валидации
        state.clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_registration_fio_cancel(self):
        from src.bot.handlers.registration import registration_fio

        message = make_message(text="❌ Отмена")
        state = AsyncMock()

        await registration_fio(message, state)

        state.clear.assert_called_once()
        message.answer.assert_called_once()
        assert "Отменено" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_registration_fio_valid_notifies_admin(self):
        from src.bot.handlers.registration import registration_fio

        message = make_message(text="Иванов Иван Иванович")
        message.from_user.id = 999
        message.from_user.username = "ivan"
        state = AsyncMock()

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()

        with (
            patch("src.bot.setup.get_bot", return_value=mock_bot),
            patch("src.bot.handlers.registration.SUPER_ADMIN_TG_ID", 777),
        ):
            await registration_fio(message, state)

        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args
        assert call_kwargs.kwargs.get("chat_id") == 777 or call_kwargs.args[0] == 777
        message.answer.assert_called_once()
        assert "отправлена" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_registration_accept_creates_user(self):
        from unittest.mock import create_autospec

        from aiogram.types import Message as AiogramMessage

        from src.bot.handlers.registration import (
            pending_registrations,
            registration_accept,
        )

        tg_id = 999
        pending_registrations[tg_id] = "Иванов Иван Иванович"

        callback = AsyncMock()
        callback.data = f"reg_accept:{tg_id}"
        # isinstance(callback.message, Message) должен быть True
        callback.message = create_autospec(AiogramMessage, instance=True)
        callback.message.text = "📋 Новая заявка"
        callback.message.edit_text = AsyncMock()

        uow = make_uow(user=None)  # пользователь ещё не существует

        mock_bot = AsyncMock()

        with (
            patch("src.bot.handlers.registration.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.registration.get_session_maker"),
            patch("src.bot.setup.get_bot", return_value=mock_bot),
        ):
            await registration_accept(callback)

        # Должен создать пользователя через репозиторий
        uow.users.create.assert_called_once()
        # Должен уведомить пользователя
        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args
        assert call_kwargs.kwargs.get("chat_id") == tg_id or call_kwargs.args[0] == tg_id

    @pytest.mark.asyncio
    async def test_registration_accept_already_registered(self):
        """Если пользователь уже зарегистрирован — не создавать дубль."""
        from unittest.mock import create_autospec

        from aiogram.types import Message as AiogramMessage

        from src.bot.handlers.registration import (
            pending_registrations,
            registration_accept,
        )

        tg_id = 888
        pending_registrations[tg_id] = "Петров Пётр Петрович"

        callback = AsyncMock()
        callback.data = f"reg_accept:{tg_id}"
        callback.message = create_autospec(AiogramMessage, instance=True)
        callback.message.text = "📋 Заявка"
        callback.message.edit_text = AsyncMock()

        existing_user = make_user(id=10, telegram_id=tg_id)
        uow = make_uow(user=existing_user)

        with (
            patch("src.bot.handlers.registration.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.registration.get_session_maker"),
        ):
            await registration_accept(callback)

        uow.users.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_registration_decline_notifies_user(self):
        from unittest.mock import create_autospec

        from aiogram.types import Message as AiogramMessage

        from src.bot.handlers.registration import registration_decline

        tg_id = 777
        callback = AsyncMock()
        callback.data = f"reg_decline:{tg_id}"
        callback.message = create_autospec(AiogramMessage, instance=True)
        callback.message.text = "📋 Заявка"
        callback.message.edit_text = AsyncMock()

        mock_bot = AsyncMock()

        with patch("src.bot.setup.get_bot", return_value=mock_bot):
            await registration_decline(callback)

        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args
        assert call_kwargs.kwargs.get("chat_id") == tg_id or call_kwargs.args[0] == tg_id
        text = call_kwargs.kwargs.get("text") or call_kwargs.args[1]
        assert "отклонена" in text


# ═══════════════════════════════════════════════════════════════════════════════
# handlers/commands.py — вспомогательные функции
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommandHelpers:
    """Тесты для _parse_id и _parse_deadline."""

    def test_parse_id_valid(self):
        from src.bot.handlers.commands import _parse_id

        assert _parse_id("42") == 42
        assert _parse_id("  7  ") == 7

    def test_parse_id_invalid(self):
        from src.bot.handlers.commands import _parse_id

        assert _parse_id("abc") is None
        assert _parse_id("") is None
        assert _parse_id(None) is None

    def test_parse_deadline_with_time(self):
        from src.bot.handlers.commands import _parse_deadline

        dt = _parse_deadline("25.06.2025 18:00")
        assert dt is not None
        assert dt.day == 25
        assert dt.month == 6
        assert dt.hour == 18
        assert dt.minute == 0

    def test_parse_deadline_date_only(self):
        from src.bot.handlers.commands import _parse_deadline

        dt = _parse_deadline("25.06.2025")
        assert dt is not None
        assert dt.hour == 9  # по умолчанию 09:00
        assert dt.minute == 0

    def test_parse_deadline_invalid(self):
        from src.bot.handlers.commands import _parse_deadline

        assert _parse_deadline("not-a-date") is None
        assert _parse_deadline("32.13.2025") is None


# ═══════════════════════════════════════════════════════════════════════════════
# handlers/commands.py — Level 1
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommandsDone:
    """/done и /undone."""

    @pytest.mark.asyncio
    async def test_done_no_args_shows_hint(self):
        from src.bot.handlers.commands import cmd_done

        message = make_message()
        command = make_command_object(None)

        await cmd_done(message, command)

        message.answer.assert_called_once()
        assert "/done" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_done_invalid_id_shows_hint(self):
        from src.bot.handlers.commands import cmd_done

        message = make_message()
        command = make_command_object("abc")

        await cmd_done(message, command)

        message.answer.assert_called_once()
        assert "/done" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_done_success(self):
        from src.bot.handlers.commands import cmd_done

        message = make_message()
        command = make_command_object("42")
        user = make_user()

        uow = make_uow(user=user)
        mock_service = AsyncMock()
        mock_service.update_task_status = AsyncMock()

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_done(message, command)

        mock_service.update_task_status.assert_called_once()
        message.answer.assert_called_once()
        assert "42" in message.answer.call_args[0][0]
        assert "выполнен" in message.answer.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_done_user_not_found(self):
        from src.bot.handlers.commands import cmd_done

        message = make_message()
        command = make_command_object("42")
        uow = make_uow(user=None)

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
        ):
            await cmd_done(message, command)

        message.answer.assert_called_once()
        assert "доступ" in message.answer.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_done_service_error_shows_message(self):
        from src.bot.handlers.commands import cmd_done

        message = make_message()
        command = make_command_object("42")
        user = make_user()
        uow = make_uow(user=user)

        mock_service = AsyncMock()
        mock_service.update_task_status = AsyncMock(side_effect=ValueError("Task not found"))

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_done(message, command)

        message.answer.assert_called_once()
        assert "Не удалось" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_undone_no_args_shows_hint(self):
        from src.bot.handlers.commands import cmd_undone

        message = make_message()
        command = make_command_object(None)

        await cmd_undone(message, command)

        assert "/undone" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_undone_success(self):
        from src.bot.handlers.commands import cmd_undone

        message = make_message()
        command = make_command_object("42")
        user = make_user()
        uow = make_uow(user=user)

        mock_service = AsyncMock()
        mock_service.update_task_status = AsyncMock()

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_undone(message, command)

        message.answer.assert_called_once()
        assert "Новая" in message.answer.call_args[0][0]


class TestCommandsTask:
    """/task — просмотр задачи."""

    @pytest.mark.asyncio
    async def test_task_no_args_shows_hint(self):
        from src.bot.handlers.commands import cmd_task

        message = make_message()
        command = make_command_object(None)

        await cmd_task(message, command)

        assert "/task" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_task_shows_full_info(self):
        from src.bot.handlers.commands import cmd_task

        message = make_message()
        command = make_command_object("42")
        user = make_user()
        task = make_task(id=42, title="Купить молоко")

        uow = make_uow(user=user)
        mock_service = AsyncMock()
        mock_service.get_task = AsyncMock(return_value=task)

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_task(message, command)

        message.answer.assert_called_once()
        text = message.answer.call_args[0][0]
        assert "42" in text
        assert "Купить молоко" in text


class TestCommandsDel:
    """/del — перемещение в корзину."""

    @pytest.mark.asyncio
    async def test_del_no_args_shows_hint(self):
        from src.bot.handlers.commands import cmd_del

        message = make_message()
        command = make_command_object(None)

        await cmd_del(message, command)

        assert "/del" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_del_success(self):
        from src.bot.handlers.commands import cmd_del

        message = make_message()
        command = make_command_object("42")
        user = make_user()
        uow = make_uow(user=user)

        mock_service = AsyncMock()
        mock_service.delete_task = AsyncMock()

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_del(message, command)

        mock_service.delete_task.assert_called_once()
        assert "корзину" in message.answer.call_args[0][0].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# handlers/commands.py — Level 2
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommandsMy:
    """/my — мои задачи."""

    @pytest.mark.asyncio
    async def test_my_no_tasks(self):
        from src.bot.handlers.commands import cmd_my

        message = make_message()
        user = make_user()
        uow = make_uow(user=user)

        mock_service = AsyncMock()
        mock_service.filter_tasks = AsyncMock(return_value=[])

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_my(message)

        assert "нет задач" in message.answer.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_my_with_tasks(self):
        from src.bot.handlers.commands import cmd_my

        message = make_message()
        user = make_user()
        uow = make_uow(user=user)
        tasks = [make_task(id=i, title=f"Task {i}") for i in range(1, 4)]

        mock_service = AsyncMock()
        mock_service.filter_tasks = AsyncMock(return_value=tasks)

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_my(message)

        text = message.answer.call_args[0][0]
        assert "Мои задачи" in text
        assert "Task 1" in text


class TestCommandsStats:
    """/stats — статистика."""

    @pytest.mark.asyncio
    async def test_stats_shows_numbers(self):
        from src.bot.handlers.commands import cmd_stats

        message = make_message()
        user = make_user()
        uow = make_uow(user=user)

        stats = {
            "total": 10,
            "done": 7,
            "pending": 3,
            "percent": 70,
            "a_total": 5,
            "a_done": 3,
            "tasks": [{"id": 1, "title": "Task 1", "status": "done"}],
        }

        mock_service = AsyncMock()
        mock_service.get_user_stats = AsyncMock(return_value=stats)

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_stats(message)

        text = message.answer.call_args[0][0]
        assert "10" in text
        assert "70" in text
        assert "Task 1" in text


# ═══════════════════════════════════════════════════════════════════════════════
# handlers/commands.py — Level 3 (/new)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommandNew:
    """/new — создание задачи одной командой."""

    @pytest.mark.asyncio
    async def test_new_no_args(self):
        from src.bot.handlers.commands import cmd_new

        message = make_message()
        command = make_command_object(None)

        await cmd_new(message, command)

        text = message.answer.call_args[0][0]
        assert "название" in text.lower()

    @pytest.mark.asyncio
    async def test_new_invalid_deadline(self):
        from src.bot.handlers.commands import cmd_new

        message = make_message()
        command = make_command_object("Задача | not-a-date")

        await cmd_new(message, command)

        text = message.answer.call_args[0][0]
        assert "дат" in text.lower()

    @pytest.mark.asyncio
    async def test_new_title_only(self):
        from src.bot.handlers.commands import cmd_new

        message = make_message()
        command = make_command_object("Купить молоко")
        user = make_user()
        task = make_task(id=5, title="Купить молоко")

        uow = make_uow(user=user)
        uow.tasks.create = AsyncMock(return_value=task)
        uow.session.flush = AsyncMock()

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.notify_task_assigned"),
            patch("src.bot.handlers.commands.asyncio.create_task"),
        ):
            await cmd_new(message, command)

        text = message.answer.call_args[0][0]
        assert "создана" in text.lower()
        assert "Купить молоко" in text

    @pytest.mark.asyncio
    async def test_new_with_deadline(self):
        from src.bot.handlers.commands import cmd_new

        message = make_message()
        command = make_command_object("Сдать отчёт | 25.12.2025 18:00")
        user = make_user()
        task = make_task(id=6, title="Сдать отчёт")

        uow = make_uow(user=user)
        uow.tasks.create = AsyncMock(return_value=task)
        uow.session.flush = AsyncMock()

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.notify_task_assigned"),
            patch("src.bot.handlers.commands.asyncio.create_task"),
        ):
            await cmd_new(message, command)

        # Проверяем что deadline попал в созданную задачу
        created_task_arg = uow.tasks.create.call_args[0][0]
        assert created_task_arg.deadline is not None

    @pytest.mark.asyncio
    async def test_new_assigned_user_not_found(self):
        from src.bot.handlers.commands import cmd_new

        message = make_message()
        command = make_command_object("Задача | 25.12.2025 | @nonexistent")
        user = make_user()

        uow = make_uow(user=user)
        uow.users.get_by_username = AsyncMock(return_value=None)
        # убрали uow.session.flush — он не нужен, до него не дойдёт

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
        ):
            await cmd_new(message, command)

        text = message.answer.call_args[0][0]
        assert "не найден" in text.lower()

    @pytest.mark.asyncio
    async def test_new_with_assignee(self):
        from src.bot.handlers.commands import cmd_new

        message = make_message()
        command = make_command_object("Позвонить | 25.12.2025 | @ivan")
        user = make_user(id=1)
        assignee = make_user(id=2, username="ivan")
        task = make_task(id=7, title="Позвонить")

        uow = make_uow(user=user)
        uow.users.get_by_username = AsyncMock(return_value=assignee)
        uow.tasks.create = AsyncMock(return_value=task)
        uow.session.flush = AsyncMock()

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.notify_task_assigned"),
            patch("src.bot.handlers.commands.asyncio.create_task"),
        ):
            await cmd_new(message, command)

        created = uow.tasks.create.call_args[0][0]
        assert created.user_id == assignee.id


# ═══════════════════════════════════════════════════════════════════════════════
# handlers/commands.py — Level 4 (/find, /group)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommandFind:
    """/find — поиск задач."""

    @pytest.mark.asyncio
    async def test_find_no_query(self):
        from src.bot.handlers.commands import cmd_find

        message = make_message()
        command = make_command_object(None)

        await cmd_find(message, command)

        assert "/find" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_find_no_results(self):
        from src.bot.handlers.commands import cmd_find

        message = make_message()
        command = make_command_object("несуществующее")
        user = make_user()
        uow = make_uow(user=user)

        mock_service = AsyncMock()
        mock_service.filter_tasks = AsyncMock(return_value=[])

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_find(message, command)

        assert "не найдено" in message.answer.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_find_with_results(self):
        from src.bot.handlers.commands import cmd_find

        message = make_message()
        command = make_command_object("отчёт")
        user = make_user()
        uow = make_uow(user=user)

        tasks = [
            make_task(id=1, title="Сдать отчёт", description="годовой"),
            make_task(id=2, title="Другая задача", description="отчёт по проекту"),
        ]

        mock_service = AsyncMock()
        mock_service.filter_tasks = AsyncMock(return_value=tasks)

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_find(message, command)

        text = message.answer.call_args[0][0]
        assert "Сдать отчёт" in text
        assert "Другая задача" in text

    @pytest.mark.asyncio
    async def test_find_filters_by_substring(self):
        """Убеждаемся, что фильтрация по подстроке работает корректно."""
        from src.bot.handlers.commands import cmd_find

        message = make_message()
        command = make_command_object("молоко")
        user = make_user()
        uow = make_uow(user=user)

        tasks = [
            make_task(id=1, title="Купить молоко", description=""),
            make_task(id=2, title="Позвонить маме", description=""),  # не совпадает
        ]

        mock_service = AsyncMock()
        mock_service.filter_tasks = AsyncMock(return_value=tasks)

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_find(message, command)

        text = message.answer.call_args[0][0]
        assert "Купить молоко" in text
        assert "Позвонить маме" not in text


class TestCommandGroup:
    """/group — задачи группы."""

    @pytest.mark.asyncio
    async def test_group_no_args(self):
        from src.bot.handlers.commands import cmd_group

        message = make_message()
        command = make_command_object(None)

        await cmd_group(message, command)

        assert "/group" in message.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_group_not_found(self):
        from src.bot.handlers.commands import cmd_group

        message = make_message()
        command = make_command_object("99")
        user = make_user()
        uow = make_uow(user=user, group=None)

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
        ):
            await cmd_group(message, command)

        assert "не найдена" in message.answer.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_group_no_tasks(self):
        from src.bot.handlers.commands import cmd_group

        message = make_message()
        command = make_command_object("3")
        user = make_user()

        group = MagicMock()
        group.name = "Разработка"
        uow = make_uow(user=user, group=group)

        mock_service = AsyncMock()
        mock_service.filter_tasks = AsyncMock(return_value=[])

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_group(message, command)

        assert "нет задач" in message.answer.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_group_shows_tasks(self):
        from src.bot.handlers.commands import cmd_group

        message = make_message()
        command = make_command_object("3")
        user = make_user()

        group = MagicMock()
        group.name = "Разработка"
        uow = make_uow(user=user, group=group)

        tasks = [make_task(id=1, title="Задача группы")]
        mock_service = AsyncMock()
        mock_service.filter_tasks = AsyncMock(return_value=tasks)

        with (
            patch("src.bot.handlers.commands.UnitOfWork", return_value=uow),
            patch("src.bot.handlers.commands.get_session_maker"),
            patch("src.bot.handlers.commands.make_task_service", return_value=mock_service),
        ):
            await cmd_group(message, command)

        text = message.answer.call_args[0][0]
        assert "Разработка" in text
        assert "Задача группы" in text


# ═══════════════════════════════════════════════════════════════════════════════
# handlers/commands.py — форматирование
# ═══════════════════════════════════════════════════════════════════════════════


class TestFormatting:
    """Тесты для функций форматирования."""

    def test_fmt_short_contains_title_and_id(self):
        from src.bot.handlers.commands import _fmt_short

        task = make_task(id=99, title="Тестовая задача", status_value="todo")
        result = _fmt_short(task)
        assert "Тестовая задача" in result
        assert "99" in result

    def test_fmt_short_status_emoji_done(self):
        from src.bot.handlers.commands import _fmt_short

        task = make_task(status_value="done")
        result = _fmt_short(task)
        assert "✅" in result

    def test_fmt_full_contains_all_fields(self):
        from src.bot.handlers.commands import _fmt_full

        task = make_task(
            id=1,
            title="Полная задача",
            description="Описание",
            status_value="in_progress",
            author_username="admin",
        )
        result = _fmt_full(task)
        assert "Полная задача" in result
        assert "Описание" in result
        assert "admin" in result
        assert "В работе" in result

    def test_fmt_deadline_none(self):
        from src.bot.handlers.commands import _fmt_deadline

        task = make_task(deadline=None)
        assert "без дедлайна" in _fmt_deadline(task)
