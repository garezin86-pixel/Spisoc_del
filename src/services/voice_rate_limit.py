# src/services/voice_rate_limit.py
"""
Rate-limit на голосовые команды бота.

Каждая голосовая команда — минимум ДВА платных вызова Groq (Whisper STT +
LLaMA tool calling, см. voice_ai.py). Без лимита один активный или
недобросовестный пользователь может неожиданно раздуть счёт за Groq API —
особенно важно для self-hosted-инстансов, где это уже не свой собственный
трафик, а чужой и непредсказуемый.

Fixed-window счётчик в Redis, тот же принцип, что и в chat_memory.py (INCR +
EXPIRE на первом хите окна). Fail-open при ошибках Redis — так же, как
chat_memory.get_history() уже тихо возвращает [] при недоступном Redis:
это cost-protection надстройка, а не критичная для работы часть, и голосовые
команды не должны молча переставать работать целиком только из-за того, что
Redis временно недоступен (при полном падении Redis и так сломается многое
другое — не хотим добавлять к этому ещё и рабочие голосовые команды).
"""

import logging

from src.core.config import VOICE_RATE_LIMIT_COUNT, VOICE_RATE_LIMIT_WINDOW_SECONDS
from src.core.redis import redis

logger = logging.getLogger(__name__)


def _key(user_id: int) -> str:
    return f"voice_rate_limit:{user_id}"


async def check_voice_rate_limit(user_id: int) -> tuple[bool, int]:
    """
    Возвращает (allowed, retry_after_seconds).

    allowed=False, если пользователь уже отправил VOICE_RATE_LIMIT_COUNT
    голосовых команд за последние VOICE_RATE_LIMIT_WINDOW_SECONDS секунд.
    retry_after_seconds — через сколько секунд лимит сбросится (0, если
    allowed=True).
    """
    key = _key(user_id)
    try:
        count = await redis.incr(key)
        if count == 1:
            # Первый хит в новом окне — выставляем TTL. Если бы это было
            # сделано отдельной командой ДО incr, была бы гонка: два
            # параллельных голосовых сообщения могли бы оба увидеть "ключа
            # ещё нет" и оба попытаться создать его с TTL, но между incr и
            # expire гонки уже нет — expire идёт после того, как мы уже
            # знаем результат incr для ЭТОГО конкретного запроса.
            await redis.expire(key, VOICE_RATE_LIMIT_WINDOW_SECONDS)

        if count > VOICE_RATE_LIMIT_COUNT:
            ttl = await redis.ttl(key)
            return False, max(ttl, 0)

        return True, 0
    except Exception as e:
        logger.warning("voice rate limit check error (fail-open, разрешаем): %s", e)
        return True, 0
