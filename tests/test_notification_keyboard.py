# tests/test_notification_keyboard.py
"""
Регресс: кнопка "📋 Открыть задачу" в уведомлениях вела на
https://t.me/?start=task_N (без юзернейма бота) — никуда не ведущая ссылка.

Причина: get_bot_username() кэширует юзернейм в module-level переменной
src/bot/setup.py::_bot_username, которая заполняется только в процессе
самого Telegram-бота (start_bot()). API и бот — разные процессы (см.
run2.py), поэтому в процессе FastAPI этот кэш всегда был пустым, если
явно не проинициализировать его в lifespan (см. src/main.py).

Тесты фиксируют оба слоя защиты:
1. task_action_keyboard() не показывает кнопку с URL, если юзернейм неизвестен
   (вместо битой ссылки).
2. main.py импортирует и готов вызвать init_bot_username() при старте.
"""

from unittest.mock import patch

from src.bot.keyboards.notification_keyboard import task_action_keyboard


class TestTaskActionKeyboard:
    def test_omits_open_task_button_when_username_unknown(self):
        """До возможной инициализации get_bot_username() возвращает "" —
        кнопка со ссылкой не должна попадать в клавиатуру вовсе."""
        with patch("src.bot.keyboards.notification_keyboard.get_bot_username", return_value=""):
            kb = task_action_keyboard(task_id=124)

        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "📋 Открыть задачу" not in all_texts
        # остальные кнопки при этом остаются на месте
        assert "✅ Выполнено" in all_texts
        assert "💬 Комментировать" in all_texts

    def test_includes_valid_deep_link_when_username_known(self):
        with patch("src.bot.keyboards.notification_keyboard.get_bot_username", return_value="Spisokdelbot"):
            kb = task_action_keyboard(task_id=124)

        buttons = [btn for row in kb.inline_keyboard for btn in row]
        open_btn = next((b for b in buttons if b.text == "📋 Открыть задачу"), None)

        assert open_btn is not None
        assert open_btn.url == "https://t.me/Spisokdelbot?start=task_124"
        # Юзернейм не пустой — в ссылке не должно быть "t.me/?start=..."
        assert "t.me/?start=" not in open_btn.url


class TestMainLifespanInitializesBotUsername:
    """API-процесс должен сам инициализировать кэш юзернейма бота при
    старте — иначе кнопки уведомлений, отправленных из FastAPI (see
    src/services/notifications.py), всегда получают пустой username."""

    def test_main_imports_init_bot_username(self):
        import inspect

        import src.main as main_module

        assert hasattr(main_module, "init_bot_username"), (
            "src/main.py должен импортировать init_bot_username из src.bot.setup "
            "и вызывать его в lifespan(), иначе get_bot_username() в процессе API "
            "всегда пустой"
        )
        source = inspect.getsource(main_module.lifespan)
        assert "init_bot_username" in source
