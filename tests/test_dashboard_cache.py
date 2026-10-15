# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_dashboard_cache.py
"""Этап 4 lite-CRM, шаг 2: кэш дашборда в Redis (ключ на компанию/пользователя/пояс/пороги, TTL 45 с).

Redis подменяется fakeredis; без него (и в обычных тестах, где cache_manager.testing=True) кэш выключен.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fakeredis import FakeAsyncRedis

from src.db.dashboard_invalidation import _PENDING_KEY
from src.models.task import SpisokModel
from src.utils.cache_manager import cache_manager
from src.utils.dashboard_cache import DASHBOARD_TTL_SECONDS, dashboard_cache, dashboard_key
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


@pytest.fixture
async def redis():
    fake = FakeAsyncRedis()
    cache_manager.redis = fake
    cache_manager.testing = False
    yield fake
    await fake.aclose()


async def _dash(client, headers, **params):
    resp = await client.get("/api/dashboard", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _add_task_today_bypassing_hook(world, title):
    """Добавляет задачу «мимо» слушателя инвалидации — как массовый UPDATE/INSERT, который в flush не попадает.
    Обычный коммит сам сбросил бы кэш (см. test_dashboard_invalidation.py), а здесь проверяется именно кэш."""
    maker, ids, _ = world
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    async with maker() as s:
        s.add(
            SpisokModel(
                title=title,
                author_id=ids["a_admin"],
                user_id=ids["owner"],
                deadline=start + timedelta(hours=1),
                workspace_id=ids["a"],
            )
        )
        await s.flush()
        s.info.pop(_PENDING_KEY, None)  # забыть, что в flush были «дашбордные» записи
        await s.commit()


async def test_second_request_is_served_from_cache(client, world, redis):
    _, ids, logins = world
    h = await _headers(client, logins, "owner")
    first = await _dash(client, h)
    second = await _dash(client, h)
    assert first["cached"] is False and second["cached"] is True
    assert second["generated_at"] == first["generated_at"]
    key = dashboard_key(ids["a"], ids["owner"], "UTC", 14, 7)
    assert 0 < await redis.ttl(key) <= DASHBOARD_TTL_SECONDS


async def test_cache_hides_changes_until_invalidated(client, world, redis):
    _, ids, logins = world
    h = await _headers(client, logins, "owner")
    assert (await _dash(client, h))["tasks_today"]["total"] == 0
    await _add_task_today_bypassing_hook(world, "новая")

    assert (await _dash(client, h))["tasks_today"]["total"] == 0  # из кэша
    assert await dashboard_cache.invalidate_user(ids["a"], ids["owner"]) == 1
    fresh = await _dash(client, h)
    assert fresh["cached"] is False and fresh["tasks_today"]["total"] == 1


async def test_key_depends_on_zone_and_thresholds(client, world, redis):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    await _dash(client, h)
    for params in ({"tz": "Europe/Kyiv"}, {"stale_days": 30}, {"events_days": 14}):
        assert (await _dash(client, h, **params))["cached"] is False
        assert (await _dash(client, h, **params))["cached"] is True


async def test_manager_and_owner_share_the_same_users_cache(client, world, redis):
    _, ids, logins = world
    await _dash(client, await _headers(client, logins, "owner"))
    seen = await _dash(client, await _headers(client, logins, "a_manager"), user_id=ids["owner"])
    assert seen["cached"] is True and seen["user_id"] == ids["owner"]


async def test_cache_does_not_bypass_permissions_or_validation(client, world, redis):
    _, ids, logins = world
    await _dash(client, await _headers(client, logins, "owner"))
    h_other = await _headers(client, logins, "other")
    assert (await client.get("/api/dashboard", params={"user_id": ids["owner"]}, headers=h_other)).status_code == 403
    assert (await client.get("/api/dashboard", params={"tz": "Mars/Base"}, headers=h_other)).status_code == 422


async def test_invalidate_workspace_leaves_other_company(client, world, redis):
    _, ids, logins = world
    await _dash(client, await _headers(client, logins, "owner"))
    await _dash(client, await _headers(client, logins, "other"))
    await _dash(client, await _headers(client, logins, "b_admin"))

    assert await dashboard_cache.invalidate_workspace(ids["a"]) == 2
    assert [k async for k in redis.scan_iter(match=f"dashboard:{ids['b']}:*")] != []
    assert (await _dash(client, await _headers(client, logins, "owner")))["cached"] is False


async def test_redis_failure_is_a_miss_not_an_error(client, world):
    _, _, logins = world

    class BrokenRedis:
        async def get(self, *args, **kwargs):
            raise ConnectionError("redis is down")

        set = get

        async def scan_iter(self, *args, **kwargs):
            raise ConnectionError("redis is down")
            yield  # noqa: B901  (делает метод асинхронным генератором, как у настоящего клиента)

    cache_manager.redis = BrokenRedis()
    cache_manager.testing = False
    h = await _headers(client, logins, "owner")
    assert (await _dash(client, h))["cached"] is False
    assert (await _dash(client, h))["cached"] is False
    assert await dashboard_cache.invalidate_user(1, 1) == 0


async def test_cache_disabled_in_testing_mode(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")  # cache_manager.testing=True по умолчанию в тестах
    assert (await _dash(client, h))["cached"] is False
    assert (await _dash(client, h))["cached"] is False
