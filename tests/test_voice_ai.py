# tests/test_voice_ai.py
"""
Тесты для src/services/voice_ai.py — голосовые команды бота (Groq Whisper + LLaMA).

Groq-клиент везде мокается: реальные сетевые вызовы недопустимы в юнит-тестах,
а сам код между вызовами Groq — это транскрипция, разбор JSON аргументов
инструментов и построение system-prompt с датами, что вполне тестируется без сети.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.services.voice_ai import (
    _system_prompt,
    call_llm_with_tools,
    process_voice_message,
    transcribe_voice,
)


def make_tool_call(name: str, arguments: dict):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))


def make_chat_response(finish_reason="tool_calls", tool_calls=None, content=None):
    message = SimpleNamespace(tool_calls=tool_calls, content=content)
    choice = SimpleNamespace(finish_reason=finish_reason, message=message)
    return SimpleNamespace(choices=[choice])


@pytest.fixture
def mock_groq():
    with patch("src.services.voice_ai._get_groq") as mock_get_groq:
        client = AsyncMock()
        mock_get_groq.return_value = client
        yield client


class TestGetGroqSingleton:
    def test_returns_same_client_on_repeated_calls(self):
        import src.services.voice_ai as voice_ai_module

        # Сбрасываем синглтон, чтобы тест не зависел от порядка запуска
        voice_ai_module._groq_client = None
        try:
            client1 = voice_ai_module._get_groq()
            client2 = voice_ai_module._get_groq()
            assert client1 is client2
        finally:
            voice_ai_module._groq_client = None


class TestTranscribeVoice:
    @pytest.mark.asyncio
    async def test_returns_plain_string_response(self, mock_groq):
        mock_groq.audio.transcriptions.create = AsyncMock(return_value="создай задачу купить молоко")

        result = await transcribe_voice(b"fake-ogg-bytes")

        assert result == "создай задачу купить молоко"

    @pytest.mark.asyncio
    async def test_returns_text_attribute_when_response_is_object(self, mock_groq):
        response_obj = SimpleNamespace(text="  найди задачи на завтра  ")
        mock_groq.audio.transcriptions.create = AsyncMock(return_value=response_obj)

        result = await transcribe_voice(b"fake-ogg-bytes")

        assert result == "найди задачи на завтра"

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_string_response(self, mock_groq):
        mock_groq.audio.transcriptions.create = AsyncMock(return_value="  текст с пробелами  \n")

        result = await transcribe_voice(b"x")

        assert result == "текст с пробелами"

    @pytest.mark.asyncio
    async def test_calls_groq_with_correct_params(self, mock_groq):
        mock_groq.audio.transcriptions.create = AsyncMock(return_value="text")

        await transcribe_voice(b"audio-data")

        call_kwargs = mock_groq.audio.transcriptions.create.call_args.kwargs
        assert call_kwargs["model"] == "whisper-large-v3"
        assert call_kwargs["language"] == "ru"
        assert call_kwargs["response_format"] == "text"
        # Файл передаётся как (filename, file_object, mime_type)
        filename, _file_obj, mime_type = call_kwargs["file"]
        assert filename == "voice.ogg"
        assert mime_type == "audio/ogg"

    @pytest.mark.asyncio
    async def test_deletes_temp_file_after_success(self, mock_groq):
        mock_groq.audio.transcriptions.create = AsyncMock(return_value="text")
        captured_path = {}

        original_unlink = os.unlink

        def spy_unlink(path):
            captured_path["path"] = path
            return original_unlink(path)

        # ВАЖНО: патчим "os.unlink", а не "src.services.voice_ai.os.unlink".
        # os — обычный import os в voice_ai.py, а не отдельный атрибут модуля,
        # который можно адресовать составным путём через resolve_name (в Python 3.13
        # обновлённый unittest.mock иначе резолвит такие пути и падает с
        # AttributeError: module 'src.services.voice_ai' has no attribute 'os').
        # os — синглтон в sys.modules, патч на "os.unlink" перехватывает вызов
        # везде, включая внутри voice_ai.py.
        with patch("os.unlink", side_effect=spy_unlink) as mock_unlink:
            await transcribe_voice(b"audio-data")

        mock_unlink.assert_called_once()
        assert not os.path.exists(captured_path["path"])

    @pytest.mark.asyncio
    async def test_deletes_temp_file_even_when_groq_raises(self, mock_groq):
        """
        Регрессионный тест: раньше временный .ogg-файл никогда не удалялся
        (delete=False без явной очистки), из-за чего на диске копился мусор
        при каждой голосовой команде. os.unlink должен вызываться в finally —
        в том числе если сам запрос к Groq упал с ошибкой.
        """
        mock_groq.audio.transcriptions.create = AsyncMock(side_effect=Exception("Groq API timeout"))

        with patch("os.unlink") as mock_unlink:
            with pytest.raises(Exception, match="Groq API timeout"):
                await transcribe_voice(b"audio-data")

        mock_unlink.assert_called_once()

    @pytest.mark.asyncio
    async def test_temp_file_actually_removed_from_disk(self, mock_groq):
        """
        Сквозная проверка без моков os.unlink: реальный файл реально исчезает.

        Раньше это проверялось диффом `glob(tempfile.gettempdir())` до/после —
        на Windows это нестабильно (антивирус/индексатор может на мгновение
        держать хендл, в системном temp также могут появляться посторонние
        файлы от параллельных процессов). Вместо этого просто фиксируем
        конкретный путь через spy на os.unlink и проверяем именно его.
        """
        mock_groq.audio.transcriptions.create = AsyncMock(return_value="text")
        captured_path = {}
        original_unlink = os.unlink

        def spy_unlink(path):
            captured_path["path"] = path
            return original_unlink(path)

        with patch("os.unlink", side_effect=spy_unlink):
            await transcribe_voice(b"audio-data")

        assert "path" in captured_path
        assert not os.path.exists(captured_path["path"])


class TestSystemPrompt:
    def test_contains_todays_date(self):
        from datetime import date

        prompt = _system_prompt()

        assert date.today().isoformat() in prompt

    def test_contains_tool_usage_hints(self):
        prompt = _system_prompt()

        assert "create_task" in prompt
        assert "get_tasks" in prompt
        assert "update_task_status" in prompt
        assert "update_task_priority" in prompt
        assert "assign_task" in prompt
        assert "update_task_description" in prompt

    def test_friday_is_always_in_the_future_or_today(self):
        from datetime import date, timedelta

        prompt = _system_prompt()
        today = date.today()
        friday = today + timedelta(days=(4 - today.weekday()) % 7)

        assert friday.isoformat() in prompt
        assert friday >= today


class TestCallLlmWithTools:
    @pytest.mark.asyncio
    async def test_returns_single_tool_call(self, mock_groq):
        tool_call = make_tool_call("create_task", {"title": "Купить молоко"})
        mock_groq.chat.completions.create = AsyncMock(
            return_value=make_chat_response(finish_reason="tool_calls", tool_calls=[tool_call])
        )

        result = await call_llm_with_tools("создай задачу купить молоко", history=[])

        assert result == [{"name": "create_task", "arguments": {"title": "Купить молоко"}}]

    @pytest.mark.asyncio
    async def test_returns_multiple_tool_calls(self, mock_groq):
        tc1 = make_tool_call("update_task_status", {"search": "молоко", "status": "done"})
        tc2 = make_tool_call("get_tasks", {"status": "todo"})
        mock_groq.chat.completions.create = AsyncMock(
            return_value=make_chat_response(finish_reason="tool_calls", tool_calls=[tc1, tc2])
        )

        result = await call_llm_with_tools("закрой молоко и покажи новые", history=[])

        assert len(result) == 2
        assert result[0]["name"] == "update_task_status"
        assert result[1]["name"] == "get_tasks"

    @pytest.mark.asyncio
    async def test_invalid_json_arguments_fall_back_to_empty_dict(self, mock_groq):
        broken_tool_call = SimpleNamespace(function=SimpleNamespace(name="get_tasks", arguments="{not valid json"))
        mock_groq.chat.completions.create = AsyncMock(
            return_value=make_chat_response(finish_reason="tool_calls", tool_calls=[broken_tool_call])
        )

        result = await call_llm_with_tools("покажи задачи", history=[])

        assert result == [{"name": "get_tasks", "arguments": {}}]

    @pytest.mark.asyncio
    async def test_no_tool_call_returns_text_response(self, mock_groq):
        mock_groq.chat.completions.create = AsyncMock(
            return_value=make_chat_response(finish_reason="stop", tool_calls=None, content="Не понял команду")
        )

        result = await call_llm_with_tools("абракадабra", history=[])

        assert result == [{"name": "text_response", "arguments": {"text": "Не понял команду"}}]

    @pytest.mark.asyncio
    async def test_text_response_with_none_content_becomes_empty_string(self, mock_groq):
        mock_groq.chat.completions.create = AsyncMock(
            return_value=make_chat_response(finish_reason="stop", tool_calls=None, content=None)
        )

        result = await call_llm_with_tools("...", history=[])

        assert result == [{"name": "text_response", "arguments": {"text": ""}}]

    @pytest.mark.asyncio
    async def test_history_is_included_in_messages(self, mock_groq):
        mock_groq.chat.completions.create = AsyncMock(
            return_value=make_chat_response(finish_reason="stop", tool_calls=None, content="ok")
        )
        history = [
            {"role": "user", "content": "первое сообщение"},
            {"role": "assistant", "content": "первый ответ"},
        ]

        await call_llm_with_tools("новое сообщение", history=history)

        messages = mock_groq.chat.completions.create.call_args.kwargs["messages"]
        contents = [m["content"] for m in messages]
        assert "первое сообщение" in contents
        assert "первый ответ" in contents
        assert "новое сообщение" in contents

    @pytest.mark.asyncio
    async def test_history_filters_out_unknown_roles(self, mock_groq):
        mock_groq.chat.completions.create = AsyncMock(
            return_value=make_chat_response(finish_reason="stop", tool_calls=None, content="ok")
        )
        history = [
            {"role": "system", "content": "должно быть отфильтровано"},
            {"role": "tool", "content": "тоже отфильтровано"},
            {"role": "user", "content": "должно остаться"},
        ]

        await call_llm_with_tools("текст", history=history)

        messages = mock_groq.chat.completions.create.call_args.kwargs["messages"]
        contents = [m["content"] for m in messages]
        assert "должно быть отфильтровано" not in contents
        assert "тоже отфильтровано" not in contents
        assert "должно остаться" in contents

    @pytest.mark.asyncio
    async def test_system_prompt_is_first_message(self, mock_groq):
        mock_groq.chat.completions.create = AsyncMock(
            return_value=make_chat_response(finish_reason="stop", tool_calls=None, content="ok")
        )

        await call_llm_with_tools("текст", history=[])

        messages = mock_groq.chat.completions.create.call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_calls_groq_with_expected_model_and_tools(self, mock_groq):
        mock_groq.chat.completions.create = AsyncMock(
            return_value=make_chat_response(finish_reason="stop", tool_calls=None, content="ok")
        )

        await call_llm_with_tools("текст", history=[])

        call_kwargs = mock_groq.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "llama-3.3-70b-versatile"
        assert call_kwargs["tool_choice"] == "auto"
        tool_names = {t["function"]["name"] for t in call_kwargs["tools"]}
        assert "create_task" in tool_names
        assert "get_tasks" in tool_names


class TestProcessVoiceMessage:
    @pytest.mark.asyncio
    async def test_full_pipeline_returns_transcript_and_tool_calls(self, mock_groq):
        mock_groq.audio.transcriptions.create = AsyncMock(return_value="создай задачу тест")
        tool_call = make_tool_call("create_task", {"title": "тест"})
        mock_groq.chat.completions.create = AsyncMock(
            return_value=make_chat_response(finish_reason="tool_calls", tool_calls=[tool_call])
        )

        transcript, tool_calls = await process_voice_message(b"audio-bytes", history=[])

        assert transcript == "создай задачу тест"
        assert tool_calls == [{"name": "create_task", "arguments": {"title": "тест"}}]

    @pytest.mark.asyncio
    async def test_passes_transcript_to_llm_call(self, mock_groq):
        mock_groq.audio.transcriptions.create = AsyncMock(return_value="покажи мои задачи")
        mock_groq.chat.completions.create = AsyncMock(
            return_value=make_chat_response(finish_reason="stop", tool_calls=None, content="ok")
        )

        await process_voice_message(b"audio-bytes", history=[])

        messages = mock_groq.chat.completions.create.call_args.kwargs["messages"]
        assert messages[-1]["content"] == "покажи мои задачи"
