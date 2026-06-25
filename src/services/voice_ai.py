"""
src/services/voice_ai.py

Транскрибация голоса через Groq Whisper + парсинг намерения через Groq LLaMA.

Поддерживаемые намерения (intent):
- create       — создать новую задачу
- find         — найти задачу по тексту
- update_status  — изменить статус задачи
- update_priority — изменить приоритет задачи
"""

import json
import logging
import re
import tempfile
from datetime import date, timedelta

from groq import AsyncGroq

from src.core.config import GROQ_API_KEY

logger = logging.getLogger(__name__)

_groq_client: AsyncGroq | None = None


def _get_groq() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq_client


async def transcribe_voice(ogg_bytes: bytes) -> str:
    groq = _get_groq()

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp.write(ogg_bytes)
        tmp_path = tmp.name

    with open(tmp_path, "rb") as audio_file:
        response = await groq.audio.transcriptions.create(
            model="whisper-large-v3",
            file=("voice.ogg", audio_file, "audio/ogg"),
            language="ru",
            response_format="text",
        )

    text = response if isinstance(response, str) else response.text
    logger.info("Transcribed voice: %s", text[:100])
    return text.strip()


async def parse_voice_intent(text: str) -> dict:
    """
    Парсит текст в намерение + данные.

    Возвращает один из вариантов:

    create:
    {"intent": "create", "title": ..., "description": ...,
     "priority": ..., "deadline": ..., "deadline_time": ...}

    find:
    {"intent": "find", "search_query": "текст для поиска"}

    update_status:
    {"intent": "update_status", "search_query": "текст задачи",
     "status": "todo|in_progress|review|done|backlog"}

    update_priority:
    {"intent": "update_priority", "search_query": "текст задачи",
     "priority": "low|medium|high|critical"}
    """
    today = date.today()
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    tomorrow = today + timedelta(days=1)
    next_monday = today + timedelta(days=(7 - today.weekday()) % 7)

    prompt = f"""Ты — помощник таск-менеджера. Определи намерение пользователя и извлеки данные.

Сегодня: {today.isoformat()}, завтра: {tomorrow.isoformat()}, пятница: {friday.isoformat()}, пн: {next_monday.isoformat()}

Текст: "{text}"

Верни ТОЛЬКО валидный JSON без markdown, без пояснений.

Намерения:

1. СОЗДАТЬ ЗАДАЧУ — пользователь хочет создать/добавить/записать задачу:
{{"intent":"create","title":"краткое название","description":"детали или null","priority":"low|medium|high|critical","deadline":"YYYY-MM-DD или null","deadline_time":"HH:MM или null"}}

2. НАЙТИ ЗАДАЧУ — пользователь ищет/хочет найти/показать задачу:
{{"intent":"find","search_query":"ключевые слова для поиска"}}

3. ИЗМЕНИТЬ СТАТУС — пользователь хочет обновить статус задачи:
{{"intent":"update_status","search_query":"ключевые слова задачи","status":"todo|in_progress|review|done|backlog"}}

4. ИЗМЕНИТЬ ПРИОРИТЕТ — пользователь хочет изменить приоритет задачи:
{{"intent":"update_priority","search_query":"ключевые слова задачи","priority":"low|medium|high|critical"}}

5. НАЗНАЧИТЬ ИСПОЛНИТЕЛЯ — пользователь хочет назначить/переназначить задачу кому-то:
{{"intent":"assign","search_query":"ключевые слова задачи","assignee":"имя или username исполнителя"}}

Правила статуса:
- выполнена / сделана / готово / закрыть → done
- в работе / начал / приступил / делаю → in_progress
- на проверке / проверить / ревью → review
- новая / открыть / вернуть → todo
- в очередь / отложить / backlog → backlog

Правила приоритета:
- срочно / критично / горит / ASAP → critical
- важно / высокий → high
- обычный / средний → medium
- не срочно / низкий / потом → low

Правила дедлайна (только для create):
- сегодня → {today.isoformat()}, завтра → {tomorrow.isoformat()}
- в пятницу → {friday.isoformat()}, на следующей неделе → {next_monday.isoformat()}
- "до 12" / "в 12" → deadline_time: "12:00"
- до обеда → deadline_time: "13:00"
- время не указано → deadline_time: null"""

    groq = _get_groq()
    response = await groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=300,
    )

    raw = (response.choices[0].message.content or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    if not raw:
        logger.warning("LLM returned empty response for: %s", text)
        return _create_fallback(text)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM invalid JSON: %s", raw)
        return _create_fallback(text)

    intent = parsed.get("intent")

    if intent == "create":
        if parsed.get("priority") not in {"low", "medium", "high", "critical"}:
            parsed["priority"] = "medium"
        return parsed

    if intent == "find":
        if not parsed.get("search_query"):
            parsed["search_query"] = text
        return parsed

    if intent == "update_status":
        valid_statuses = {"todo", "in_progress", "review", "done", "backlog"}
        if parsed.get("status") not in valid_statuses:
            parsed["status"] = "done"
        if not parsed.get("search_query"):
            parsed["search_query"] = text
        return parsed

    if intent == "update_priority":
        if parsed.get("priority") not in {"low", "medium", "high", "critical"}:
            parsed["priority"] = "high"
        if not parsed.get("search_query"):
            parsed["search_query"] = text
        return parsed

    if intent == "assign":
        if not parsed.get("search_query"):
            parsed["search_query"] = text
        if not parsed.get("assignee"):
            parsed["assignee"] = ""
        return parsed

    # Неизвестное намерение — fallback на create
    return _create_fallback(text)


def _create_fallback(text: str) -> dict:
    return {
        "intent": "create",
        "title": text[:100],
        "description": None,
        "priority": "medium",
        "deadline": None,
        "deadline_time": None,
    }


async def process_voice_message(ogg_bytes: bytes) -> tuple[str, dict]:
    """Полный pipeline: байты → (транскрипт, распознанное намерение)."""
    transcript = await transcribe_voice(ogg_bytes)
    intent_data = await parse_voice_intent(transcript)
    return transcript, intent_data
