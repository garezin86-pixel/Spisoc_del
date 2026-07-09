"""
src/services/voice_ai.py

STT: Groq Whisper large-v3
LLM: Groq LLaMA 3.3 70B с tool calling + memory
"""

import json
import logging
import os
import tempfile
from datetime import date, timedelta

from groq import AsyncGroq
from groq.types.chat import ChatCompletionMessageParam  # type: ignore[import]

from src.core.config import GROQ_API_KEY

logger = logging.getLogger(__name__)

_groq_client: AsyncGroq | None = None


def _get_groq() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq_client


# ── Tools definition ──────────────────────────────────────────────────────────

TOOLS: list = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Создать новую задачу",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Название задачи (до 100 символов)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Подробности задачи",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Приоритет: low/medium/high/critical",
                    },
                    "deadline": {
                        "type": "string",
                        "description": "Дедлайн в формате YYYY-MM-DD",
                    },
                    "deadline_time": {
                        "type": "string",
                        "description": "Время дедлайна HH:MM",
                    },
                    "assignee_username": {
                        "type": "string",
                        "description": "Username исполнителя (без @)",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tasks",
            "description": "Найти или показать задачи пользователя",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Текст для поиска по названию",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["todo", "in_progress", "review", "done", "backlog"],
                        "description": "Фильтр по статусу",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Фильтр по приоритету",
                    },
                    "overdue": {
                        "type": "boolean",
                        "description": "Только просроченные задачи",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_status",
            "description": "Изменить статус задачи",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Ключевые слова для поиска задачи",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["todo", "in_progress", "review", "done", "backlog"],
                        "description": "Новый статус",
                    },
                },
                "required": ["search", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_priority",
            "description": "Изменить приоритет задачи",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Ключевые слова для поиска задачи",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Новый приоритет",
                    },
                },
                "required": ["search", "priority"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_task",
            "description": "Назначить исполнителя задачи",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Ключевые слова для поиска задачи",
                    },
                    "assignee_username": {
                        "type": "string",
                        "description": "Username исполнителя (без @)",
                    },
                },
                "required": ["search", "assignee_username"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_description",
            "description": "Изменить описание задачи",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Ключевые слова для поиска задачи",
                    },
                    "description": {
                        "type": "string",
                        "description": "Новое описание задачи",
                    },
                },
                "required": ["search", "description"],
            },
        },
    },
]


# ── STT ───────────────────────────────────────────────────────────────────────


async def transcribe_voice(ogg_bytes: bytes) -> str:
    """Транскрибирует голосовое через Groq Whisper large-v3."""
    groq = _get_groq()

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp.write(ogg_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as audio_file:
            response = await groq.audio.transcriptions.create(
                model="whisper-large-v3",
                file=("voice.ogg", audio_file, "audio/ogg"),
                language="ru",
                response_format="text",
            )
    finally:
        # ВАЖНО: раньше временный файл никогда не удалялся (delete=False +
        # отсутствие явной очистки) — при каждой голосовой команде на диске
        # оставался orphan .ogg-файл. При активном использовании бота это
        # постепенно забивало диск до следующего рестарта контейнера.
        os.unlink(tmp_path)

    text = response if isinstance(response, str) else response.text
    logger.info("Transcribed: %s", text[:100])
    return text.strip()


# ── LLM с tool calling ────────────────────────────────────────────────────────


def _system_prompt() -> str:
    today = date.today()
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    tomorrow = today + timedelta(days=1)
    next_monday = today + timedelta(days=(7 - today.weekday()) % 7)

    return f"""Ты — голосовой ассистент таск-менеджера Spisok Del.
Отвечай кратко и по-русски.
Используй инструменты для выполнения команд пользователя.
Если пользователь говорит «создай», «добавь», «запиши» — используй create_task.
Если «найди», «покажи», «какие», «есть ли» — используй get_tasks.
Если «выполни», «закрой», «отметь», «в работе» — используй update_task_status.
Если «сделай срочной», «повысь приоритет», «низкий приоритет» — используй update_task_priority.
Если «назначь», «переназначь» — используй assign_task.
Если «измени описание», «добавь описание», «обнови описание» — используй update_task_description.

Сегодня: {today.isoformat()}
Завтра: {tomorrow.isoformat()}
Пятница: {friday.isoformat()}
Следующий понедельник: {next_monday.isoformat()}

Правила дедлайна: сегодня={today}, завтра={tomorrow}, до пятницы={friday}.
Правила времени: «до 12» → deadline_time=12:00, «до обеда» → 13:00.
Приоритет: срочно/горит/ASAP → critical, важно → high, обычное → medium, потом → low."""


async def call_llm_with_tools(
    text: str,
    history: list[dict],
) -> list[dict]:
    """
    Вызывает Groq LLaMA с tool calling.
    Возвращает список вызовов инструментов:
    [{"name": "create_task", "arguments": {...}}, ...]
    """
    groq = _get_groq()

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": _system_prompt()},
    ]
    for h in history:
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})  # type: ignore[arg-type]
    messages.append({"role": "user", "content": text})

    response = await groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        temperature=0.1,
        max_tokens=1024,
    )

    choice = response.choices[0]
    tool_calls = []

    if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
        for tc in choice.message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                {
                    "name": tc.function.name,
                    "arguments": args,
                }
            )
        logger.info("Tool calls: %s", [tc["name"] for tc in tool_calls])
    else:
        # LLM ответил текстом без tool call — возвращаем как есть
        content = choice.message.content or ""
        logger.info("LLM text response (no tool call): %s", content[:100])
        tool_calls.append(
            {
                "name": "text_response",
                "arguments": {"text": content},
            }
        )

    return tool_calls


# ── Pipeline ──────────────────────────────────────────────────────────────────


async def process_voice_message(
    ogg_bytes: bytes,
    history: list[dict],
) -> tuple[str, list[dict]]:
    """
    Полный pipeline: байты → (транскрипт, список tool calls).
    history — история диалога из Redis.
    """
    transcript = await transcribe_voice(ogg_bytes)
    tool_calls = await call_llm_with_tools(transcript, history)
    return transcript, tool_calls
