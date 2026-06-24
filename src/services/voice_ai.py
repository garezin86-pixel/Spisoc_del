"""
src/services/voice_ai.py

Транскрибация голоса через Groq Whisper + парсинг в задачу через Groq LLM.
Один провайдер — никаких проблем с квотами Gemini.
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
    """
    Транскрибирует голосовое сообщение через Groq Whisper large-v3.
    """
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


async def parse_task_from_text(text: str) -> dict:
    """
    Парсит произвольный текст в структуру задачи через Groq LLaMA.
    """
    today = date.today()
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    tomorrow = today + timedelta(days=1)
    next_monday = today + timedelta(days=(7 - today.weekday()) % 7)

    prompt = f"""Ты — помощник, который парсит текст в структуру задачи.

Сегодняшняя дата: {today.isoformat()}
Завтра: {tomorrow.isoformat()}
Ближайшая пятница: {friday.isoformat()}
Следующий понедельник: {next_monday.isoformat()}

Текст пользователя: "{text}"

Верни ТОЛЬКО валидный JSON без markdown-обёртки, без пояснений:
{{
  "title": "краткое название задачи (до 100 символов)",
  "description": "подробности если есть, иначе null",
  "priority": "low | medium | high | critical",
  "deadline": "YYYY-MM-DD или null",
  "deadline_time": "HH:MM или null"
}}

Правила приоритета:
- critical: срочно, ASAP, горит, немедленно, критично
- high: важно, нужно сегодня, до конца дня
- medium: обычная задача (default)
- low: когда-нибудь, не срочно, при возможности

Правила дедлайна (дата):
- "сегодня" → {today.isoformat()}
- "завтра" → {tomorrow.isoformat()}
- "в пятницу" / "до пятницы" → {friday.isoformat()}
- "на следующей неделе" → {next_monday.isoformat()}
- конкретная дата → преобразуй в YYYY-MM-DD
- не указан → null

Правила дедлайна (время):
- "до 12" / "до 12:00" / "в 12" → "12:00"
- "до 18" / "до 6 вечера" → "18:00"
- "до обеда" → "13:00"
- если время не указано → null
- время НЕ дублируй в description, оно уже есть в deadline_time"""

    groq = _get_groq()
    response = await groq.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=256,
    )

    raw = (response.choices[0].message.content or "").strip()

    # Убираем ```json ... ``` если модель всё же добавила
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    if not raw:
        logger.warning("LLM returned empty response")
        return {
            "title": text[:100],
            "description": None,
            "priority": "medium",
            "deadline": None,
        }

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON: %s", raw)
        parsed = {
            "title": text[:100],
            "description": None,
            "priority": "medium",
            "deadline": None,
        }

    # Валидация приоритета
    if parsed.get("priority") not in {"low", "medium", "high", "critical"}:
        parsed["priority"] = "medium"

    return parsed


async def process_voice_message(ogg_bytes: bytes) -> tuple[str, dict]:
    """
    Полный pipeline: байты голосового → (транскрипт, задача).
    """
    transcript = await transcribe_voice(ogg_bytes)
    task_data = await parse_task_from_text(transcript)
    return transcript, task_data
