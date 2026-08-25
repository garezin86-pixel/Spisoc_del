# tests/test_voice_rate_limit.py
"""
Тесты для src/services/voice_rate_limit.py.

Используем fakeredis (реальная семантика INCR/EXPIRE/TTL, не ручные моки
возвращаемых значений) для основной логики лимита, и AsyncMock отдельно —
для проверки fail-open поведения при реальном сбое Redis.
"""

from unittest.mock import AsyncMock

import pytest
from fakeredis import aioredis as fakeaioredis

import src.services.voice_rate_limit as voice_rate_limit
from src.services.voice_rate_limit import check_voice_rate_limit

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Подменяем модульный `redis` (плоский глобальный клиент из
    src.core.redis, тот же, что использует chat_memory.py) на fakeredis —
    реальная семантика команд, без настоящего сервера."""
    fake = fakeaioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(voice_rate_limit, "redis", fake)
    yield fake


@pytest.fixture(autouse=True)
def default_limits(monkeypatch):
    """Небольшие предсказуемые лимиты для тестов, не завязываемся на
    реальные дефолты конфига (VOICE_RATE_LIMIT_COUNT=10/600с) — это сделало
    бы тесты медленными и хрупкими."""
    monkeypatch.setattr(voice_rate_limit, "VOICE_RATE_LIMIT_COUNT", 3)
    monkeypatch.setattr(voice_rate_limit, "VOICE_RATE_LIMIT_WINDOW_SECONDS", 60)


class TestCheckVoiceRateLimit:
    async def test_first_request_is_allowed(self):
        allowed, retry_after = await check_voice_rate_limit(user_id=1)

        assert allowed is True
        assert retry_after == 0

    async def test_requests_up_to_the_limit_are_allowed(self):
        """Лимит 3 — значит 3-й запрос ещё должен пройти, только 4-й — нет."""
        for _ in range(3):
            allowed, _ = await check_voice_rate_limit(user_id=1)
            assert allowed is True

    async def test_request_exceeding_the_limit_is_blocked(self):
        for _ in range(3):
            await check_voice_rate_limit(user_id=1)

        allowed, retry_after = await check_voice_rate_limit(user_id=1)

        assert allowed is False
        assert retry_after > 0

    async def test_retry_after_does_not_exceed_window(self):
        for _ in range(4):
            allowed, retry_after = await check_voice_rate_limit(user_id=1)

        assert allowed is False
        assert 0 < retry_after <= 60

    async def test_different_users_have_independent_limits(self):
        """Регресс: ключ должен быть per-user, а не общий на всех."""
        for _ in range(3):
            await check_voice_rate_limit(user_id=1)
        blocked, _ = await check_voice_rate_limit(user_id=1)
        assert blocked is False

        # Другой пользователь — свежий лимит, не задет чужим счётчиком.
        allowed, _ = await check_voice_rate_limit(user_id=2)
        assert allowed is True

    async def test_window_expires_and_resets_the_counter(self, fake_redis):
        for _ in range(3):
            await check_voice_rate_limit(user_id=1)
        blocked, _ = await check_voice_rate_limit(user_id=1)
        assert blocked is False

        # Эмулируем истечение окна — просто удаляем ключ, как это сделал бы
        # Redis сам по TTL, не дожидаясь реального времени в тесте.
        await fake_redis.delete("voice_rate_limit:1")

        allowed, retry_after = await check_voice_rate_limit(user_id=1)
        assert allowed is True
        assert retry_after == 0

    async def test_key_is_namespaced_per_user_id(self, fake_redis):
        await check_voice_rate_limit(user_id=42)

        assert await fake_redis.exists("voice_rate_limit:42")

    async def test_sets_ttl_only_on_first_hit_in_window(self, fake_redis):
        """TTL не должен переустанавливаться на каждый запрос (иначе активный
        пользователь мог бы бесконечно продлевать себе окно и никогда не
        упереться в лимит)."""
        await check_voice_rate_limit(user_id=1)
        ttl_after_first = await fake_redis.ttl("voice_rate_limit:1")

        await check_voice_rate_limit(user_id=1)
        ttl_after_second = await fake_redis.ttl("voice_rate_limit:1")

        assert ttl_after_first > 0
        # TTL не увеличился (второй incr не должен был снова выставлять expire)
        assert ttl_after_second <= ttl_after_first


class TestFailOpenOnRedisError:
    """Если Redis недоступен — голосовые команды не должны молча
    переставать работать целиком: лимит это cost-protection надстройка,
    а не критичная для работоспособности часть (тот же принцип, что и в
    chat_memory.get_history())."""

    async def test_redis_error_on_incr_fails_open(self, monkeypatch):
        broken_redis = AsyncMock()
        broken_redis.incr = AsyncMock(side_effect=ConnectionError("Redis недоступен"))
        monkeypatch.setattr(voice_rate_limit, "redis", broken_redis)

        allowed, retry_after = await check_voice_rate_limit(user_id=1)

        assert allowed is True
        assert retry_after == 0

    async def test_redis_error_on_expire_fails_open(self, monkeypatch):
        broken_redis = AsyncMock()
        broken_redis.incr = AsyncMock(return_value=1)
        broken_redis.expire = AsyncMock(side_effect=ConnectionError("Redis недоступен"))
        monkeypatch.setattr(voice_rate_limit, "redis", broken_redis)

        allowed, retry_after = await check_voice_rate_limit(user_id=1)

        assert allowed is True
        assert retry_after == 0

    async def test_redis_error_on_ttl_when_over_limit_fails_open(self, monkeypatch):
        """Даже если incr показал превышение лимита, но последующий ttl()
        упал — всё равно fail-open, а не 'зависнуть' на ошибке."""
        broken_redis = AsyncMock()
        broken_redis.incr = AsyncMock(return_value=999)
        broken_redis.ttl = AsyncMock(side_effect=ConnectionError("Redis недоступен"))
        monkeypatch.setattr(voice_rate_limit, "redis", broken_redis)

        allowed, retry_after = await check_voice_rate_limit(user_id=1)

        assert allowed is True
        assert retry_after == 0
