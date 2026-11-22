"""
RUN_BOT_IN_API: запуск Telegram-бота внутри процесса API (Render free — нет воркеров).

По умолчанию выключено: бот остаётся отдельным процессом (src/bot/runner.py).
"""

import pytest

import src.main as main_module
from src.bot import setup as bot_setup
from src.core import config


class TestRunBotInApiSetting:
    def test_disabled_by_default(self):
        field = config.Settings.model_fields["run_bot_in_api"]
        assert field.default is False

    def test_reads_env_alias(self):
        s = config.Settings(_env_file=None, ENV="development", RUN_BOT_IN_API="true")
        assert s.run_bot_in_api is True


class TestEmbeddedBot:
    @pytest.fixture
    def calls(self, monkeypatch):
        calls = {"start": 0, "stop": 0}

        async def fake_start():
            calls["start"] += 1
            bot_setup.polling_task = object()  # "polling запущен"

        async def fake_stop():
            calls["stop"] += 1

        monkeypatch.setattr(bot_setup, "start_bot", fake_start)
        monkeypatch.setattr(bot_setup, "stop_bot", fake_stop)
        monkeypatch.setattr(bot_setup, "polling_task", None)
        return calls

    @pytest.mark.asyncio
    async def test_flag_off_does_not_start_bot(self, monkeypatch, calls):
        monkeypatch.setattr(main_module, "RUN_BOT_IN_API", False)
        monkeypatch.setattr(main_module, "BOT_TOKEN", "123:abc")

        assert await main_module._start_embedded_bot() is False
        assert calls["start"] == 0

    @pytest.mark.asyncio
    async def test_flag_on_without_token_skips(self, monkeypatch, calls):
        monkeypatch.setattr(main_module, "RUN_BOT_IN_API", True)
        monkeypatch.setattr(main_module, "BOT_TOKEN", "")

        assert await main_module._start_embedded_bot() is False
        assert calls["start"] == 0

    @pytest.mark.asyncio
    async def test_flag_on_starts_bot(self, monkeypatch, calls):
        monkeypatch.setattr(main_module, "RUN_BOT_IN_API", True)
        monkeypatch.setattr(main_module, "BOT_TOKEN", "123:abc")

        assert await main_module._start_embedded_bot() is True
        assert calls["start"] == 1

    @pytest.mark.asyncio
    async def test_start_failure_is_reported_as_not_started(self, monkeypatch, calls):
        """start_bot сам глотает ошибки и оставляет polling_task=None — это не «запущено»."""

        async def failing_start():
            bot_setup.polling_task = None

        monkeypatch.setattr(bot_setup, "start_bot", failing_start)
        monkeypatch.setattr(main_module, "RUN_BOT_IN_API", True)
        monkeypatch.setattr(main_module, "BOT_TOKEN", "123:abc")

        assert await main_module._start_embedded_bot() is False

    @pytest.mark.asyncio
    async def test_stop_only_when_started(self, calls):
        await main_module._stop_embedded_bot(False)
        assert calls["stop"] == 0

        await main_module._stop_embedded_bot(True)
        assert calls["stop"] == 1

    @pytest.mark.asyncio
    async def test_stop_error_does_not_break_shutdown(self, monkeypatch, calls):
        async def boom():
            raise RuntimeError("telegram down")

        monkeypatch.setattr(bot_setup, "stop_bot", boom)

        await main_module._stop_embedded_bot(True)  # не бросает

    def test_lifespan_wires_embedded_bot(self):
        import inspect

        source = inspect.getsource(main_module.lifespan)
        assert "_start_embedded_bot()" in source
        assert "_stop_embedded_bot(" in source
