# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_dashboard_invalidation.py
"""Этап 4 lite-CRM, шаг 3: сброс кэша дашборда и WebSocket-событие `dashboard_changed` при изменениях.

Redis — fakeredis, WebSocket-менеджер — моки: проверяем, кому и когда уходит событие и какие ключи сброшены.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fakeredis import FakeAsyncRedis

from src.db.dashboard_invalidation import EVENT_NAME, wait_idle
from src.models.client import ContactModel
from src.models.task import SpisokModel
from src.utils.cache_manager import cache_manager
from src.utils.dashboard_cache import dashboard_key
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


@pytest.fixture
async def redis():
    fake = FakeAsyncRedis()
    cache_manager.redis = fake
    cache_manager.testing = False
    yield fake
    await fake.aclose()


@pytest.fixture
def ws():
    with patch("src.core.ws_manager.ws_manager.broadcast_to_users", new=AsyncMock()) as to_users:
        with patch("src.core.ws_manager.ws_manager.broadcast_all", new=AsyncMock()) as to_all:
            yield to_users, to_all


async def _warm(client, logins, ws, *who):
    """Прогревает кэш дашбордов. Первое обращение создаёт воронку компании (это тоже коммит, который сбрасывает кэш
    компании), поэтому сначала воронка, потом прогрев, и моки сбрасываются — тест видит только свои изменения."""
    for name in who:
        assert (await client.get("/api/pipeline", headers=await _headers(client, logins, name))).status_code == 200
    await wait_idle()
    for name in who:
        resp = await client.get("/api/dashboard", headers=await _headers(client, logins, name))
        assert resp.status_code == 200, resp.text
    await wait_idle()
    for mock in ws:
        mock.reset_mock()


async def _cached_keys(redis, ids) -> set[str]:
    return {k.decode() async for k in redis.scan_iter(match="dashboard:*")}


def _key(ids, who, ws="a"):
    return dashboard_key(ids[ws], ids[who], "UTC", 14, 7)


def _task(ids, user, **kwargs):
    return SpisokModel(title="Задача", author_id=ids["a_admin"], user_id=ids[user], workspace_id=ids["a"], **kwargs)


# ── изменения, затрагивающие конкретных пользователей ────────────────────────
async def test_task_change_invalidates_only_its_assignee(client, world, redis, ws):
    maker, ids, logins = world
    to_users, to_all = ws
    await _warm(client, logins, ws, "owner", "other")

    async with maker() as s:
        s.add(_task(ids, "owner"))
        await s.commit()
    await wait_idle()

    assert await _cached_keys(redis, ids) == {_key(ids, "other")}
    to_users.assert_awaited_once_with([ids["owner"]], EVENT_NAME, {})
    to_all.assert_not_awaited()


async def test_reassigned_task_notifies_old_and_new_assignee(client, world, redis, ws):
    maker, ids, logins = world
    to_users, _ = ws
    async with maker() as s:
        task = _task(ids, "owner")
        s.add(task)
        await s.commit()
        task_id = task.id
    await wait_idle()
    await _warm(client, logins, ws, "owner", "other", "a_manager")
    to_users.reset_mock()

    async with maker() as s:
        task = await s.get(SpisokModel, task_id)
        task.user_id = ids["other"]
        await s.commit()
    await wait_idle()

    assert await _cached_keys(redis, ids) == {_key(ids, "a_manager")}
    (called_users, event, _data), _ = to_users.await_args
    assert set(called_users) == {ids["owner"], ids["other"]} and event == EVENT_NAME


async def test_scheduled_event_invalidates_its_assignee(client, world, redis, ws):
    _, ids, logins = world
    to_users, _ = ws
    await _warm(client, logins, ws, "owner", "other")
    hm = await _headers(client, logins, "a_manager")

    resp = await client.post(
        f"/api/clients/{ids['ca']}/events",
        json={"type": "call", "starts_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
              "assignee_id": ids["owner"]},
        headers=hm,
    )  # fmt: skip
    assert resp.status_code == 201, resp.text
    await wait_idle()

    assert await _cached_keys(redis, ids) == {_key(ids, "other")}
    assert ids["owner"] in to_users.await_args.args[0]


# ── изменения, затрагивающие всю компанию ────────────────────────────────────
async def test_interaction_invalidates_whole_workspace_only(client, world, redis, ws):
    _, ids, logins = world
    _, to_all = ws
    await _warm(client, logins, ws, "owner", "other", "b_admin")

    resp = await client.post(
        f"/api/clients/{ids['ca']}/interactions", json={"type": "call"}, headers=await _headers(client, logins, "owner")
    )
    assert resp.status_code == 201, resp.text
    await wait_idle()

    assert await _cached_keys(redis, ids) == {dashboard_key(ids["b"], ids["b_admin"], "UTC", 14, 7)}
    to_all.assert_awaited_once_with(EVENT_NAME, {}, workspace_id=ids["a"])


# ── когда ничего не происходит ───────────────────────────────────────────────
async def test_rollback_sends_nothing(client, world, redis, ws):
    maker, ids, logins = world
    to_users, to_all = ws
    await _warm(client, logins, ws, "owner")

    async with maker() as s:
        s.add(_task(ids, "owner"))
        await s.flush()
        await s.rollback()
    await wait_idle()

    assert await _cached_keys(redis, ids) == {_key(ids, "owner")}
    to_users.assert_not_awaited()
    to_all.assert_not_awaited()


async def test_unrelated_change_sends_nothing(client, world, redis, ws):
    maker, ids, logins = world
    to_users, to_all = ws
    await _warm(client, logins, ws, "owner")

    async with maker() as s:
        s.add(ContactModel(client_id=ids["ca"], name="Иван", workspace_id=ids["a"]))
        await s.commit()
    await wait_idle()

    assert await _cached_keys(redis, ids) == {_key(ids, "owner")}
    to_users.assert_not_awaited()
    to_all.assert_not_awaited()


async def test_notification_failure_does_not_break_commit(client, world, ws):
    maker, ids, _ = world
    to_users, _ = ws
    to_users.side_effect = RuntimeError("ws bridge down")

    async with maker() as s:
        s.add(_task(ids, "owner"))
        await s.commit()  # не должен упасть
    await wait_idle()
    to_users.assert_awaited_once()


async def test_end_to_end_dashboard_is_fresh_after_change(client, world, redis, ws):
    maker, ids, logins = world
    h = await _headers(client, logins, "owner")
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    assert (await client.get("/api/dashboard", headers=h)).json()["tasks_today"]["total"] == 0

    async with maker() as s:
        s.add(_task(ids, "owner", deadline=start + timedelta(hours=1)))
        await s.commit()
    await wait_idle()

    fresh = (await client.get("/api/dashboard", headers=h)).json()
    assert fresh["cached"] is False and fresh["tasks_today"]["total"] == 1
