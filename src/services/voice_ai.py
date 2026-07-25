"""
src/services/voice_ai.py

STT: Groq Whisper large-v3
TTS: Microsoft Edge TTS (ru-RU-DmitryNeural по умолчанию) — синтез голосовых
     уведомлений. НЕ Groq: Groq Orpheus умеет только английский (и отдельно
     саудовский арабский) — реальный прогон на русской фразе "У вас 8
     просроченных задач" дал "У вас eight просроченных задач" — числа читались
     по-английски прямо посреди русского текста. Edge TTS — бесплатный сервис
     от Microsoft (тот же движок, что в Windows Narrator/Edge browser),
     с нормальными русским и украинским голосами.
LLM: Groq LLaMA 3.3 70B с tool calling + memory
"""

import asyncio
import json
import logging
import os
import tempfile
from datetime import date, timedelta

import edge_tts
from groq import AsyncGroq
from groq.types.chat import ChatCompletionMessageParam  # type: ignore[import]

from src.core.config import GROQ_API_KEY

logger = logging.getLogger(__name__)

_groq_client: AsyncGroq | None = None

# ru-RU-DmitryNeural — мужской голос, звучит естественно для системных
# уведомлений. Женская альтернатива: ru-RU-SvetlanaNeural.
# Полный список: `edge-tts --list-voices` или edge_tts.list_voices().
DEFAULT_TTS_VOICE = "ru-RU-DmitryNeural"


def _get_groq() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq_client


async def _mp3_to_ogg_opus(mp3_bytes: bytes) -> bytes:
    """
    Перекодирует MP3 в OGG/Opus через ffmpeg — Telegram принимает как
    голосовое сообщение (`send_voice`) только Opus в контейнере OGG, а
    Edge TTS отдаёт только MP3 (формат сервиса Microsoft, без вариантов).

    ВАЖНО: требует установленный ffmpeg в системе/контейнере (см.
    Dockerfile — добавлен `apt-get install ffmpeg`). Без него этот вызов
    упадёт с FileNotFoundError.

    Раньше здесь был asyncio.create_subprocess_exec (через pipe, без
    временных файлов) — но asyncio-сабпроцессы на Windows работают ТОЛЬКО
    под ProactorEventLoop; если где-то в процессе (например, ради другой
    библиотеки) стоит asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy),
    любой create_subprocess_exec падает с "NotImplementedError" без
    дополнительного текста — именно так тихо ломалось голосовое уведомление
    в фоновой джобе APScheduler, хотя ручной asyncio.run() в REPL (со своим,
    отдельным event loop'ом на Proactor по умолчанию) отрабатывал нормально.

    Синхронный subprocess.run(), запущенный в отдельном потоке через
    run_in_executor, не зависит от типа event loop вообще — работает
    одинаково что на Proactor, что на Selector, и на Windows, и на Linux.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run_ffmpeg_sync, mp3_bytes)


def _run_ffmpeg_sync(mp3_bytes: bytes) -> bytes:
    """Синхронная часть конвертации — выполняется в executor-потоке."""
    import subprocess

    result = subprocess.run(
        [
            "ffmpeg",
            "-i",
            "pipe:0",
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            "-vbr",
            "on",
            "-f",
            "ogg",
            "pipe:1",
        ],
        input=mp3_bytes,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg mp3->ogg conversion failed: {result.stderr.decode(errors='replace')[:500]}")
    return result.stdout


async def synthesize_speech(text: str, voice: str = DEFAULT_TTS_VOICE) -> bytes:
    """
    Синтезирует речь через Microsoft Edge TTS, возвращает байты в формате
    OGG/Opus — готовом для отправки как `voice` (голосовое сообщение) в
    Telegram. Edge TTS отдаёт только MP3, поэтому внутри есть перекодирование
    через ffmpeg (см. _mp3_to_ogg_opus).

    Не ловит исключения сама — вызывающий код (бот) должен сам решить,
    как реагировать на сбой TTS (например, откатиться на обычный текст).
    """
    communicate = edge_tts.Communicate(text, voice)
    mp3_chunks = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            data = chunk.get("data")
            if data:
                mp3_chunks.append(data)
                # mp3_chunks.append(chunk["data"])

    if not mp3_chunks:
        raise RuntimeError("Edge TTS не вернул аудио (пустой ответ)")

    mp3_bytes = b"".join(mp3_chunks)
    return await _mp3_to_ogg_opus(mp3_bytes)


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
