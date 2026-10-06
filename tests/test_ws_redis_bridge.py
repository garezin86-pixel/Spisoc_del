"""WebSocket-шина между процессами: бот (отдельный процесс) → веб-клиенты в процессе API."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import fakeredis
import pytest

from src.core.ws_manager import WS_CHANNEL, WSManager

pytestmark = pytest.mark.asyncio


@pytest.fixture
def server():
    return fakeredis.FakeServer()


def _redis(server, *, decode: bool):
    return fakeredis.FakeAsyncRedis(server=server, decode_responses=decode)


async def _eventually(cond, timeout: float = 2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("условие не выполнилось за отведённое время")


def _sock():
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


def _events(ws):
    return [json.loads(c.args[0]) for c in ws.send_text.await_args_list]


@pytest.fixture
async def api(server):
    """Процесс API: держит соединения и слушает канал (как в lifespan: decode_responses=False)."""
    mgr = WSManager()
    await mgr.start_redis_bridge(_redis(server, decode=False), listen=True)
    yield mgr
    await mgr.stop_redis_bridge()


@pytest.fixture
async def bot(server):
    """Процесс бота: соединений нет, только публикует (как src.core.redis.redis: decode_responses=True)."""
    mgr = WSManager()
    await mgr.start_redis_bridge(_redis(server, decode=True), listen=False)
    yield mgr
    await mgr.stop_redis_bridge()


async def test_bot_broadcast_all_reaches_only_target_company_in_api_process(api, bot):
    mine, other = _sock(), _sock()
    await api.connect(mine, 1, 10)
    await api.connect(other, 2, 20)

    await bot.broadcast_all("chat_message", {"text": "из Telegram"}, workspace_id=10)

    await _eventually(lambda: mine.send_text.await_count == 1)
    await asyncio.sleep(0.1)  # чужая компания не получает и «позже»
    assert _events(mine) == [{"event": "chat_message", "data": {"text": "из Telegram"}}]
    other.send_text.assert_not_awaited()


async def test_bot_broadcast_to_users_reaches_listed_users_only(api, bot):
    a, b, c = _sock(), _sock(), _sock()
    await api.connect(a, 1, 10)
    await api.connect(b, 2, 10)
    await api.connect(c, 3, 10)

    await bot.broadcast_to_users([1, 3], "chat_message", {"n": 1})

    await _eventually(lambda: a.send_text.await_count == 1 and c.send_text.await_count == 1)
    await asyncio.sleep(0.1)
    b.send_text.assert_not_awaited()


async def test_bot_disconnect_user_closes_socket_in_api_process(api, bot):
    ws, bystander = _sock(), _sock()
    await api.connect(ws, 1, 10)
    await api.connect(bystander, 2, 10)

    # Раньше вызов шёл в пустой WSManager бота и ничего не делал.
    assert await bot.disconnect_user(1) == 0  # число закрытых в процессе бота неизвестно/равно 0

    await _eventually(lambda: ws.close.await_count == 1)
    assert ws.close.await_args.kwargs["code"] == 4001
    bystander.close.assert_not_awaited()
    assert api.total_connections == 1


async def test_bot_disconnect_workspace_closes_only_that_company(api, bot):
    mine, other = _sock(), _sock()
    await api.connect(mine, 1, 10)
    await api.connect(other, 2, 20)

    await bot.disconnect_workspace(10)

    await _eventually(lambda: mine.close.await_count == 1)
    await asyncio.sleep(0.1)
    other.close.assert_not_awaited()


async def test_api_process_also_goes_through_the_bridge(api):
    """Публикация из самого API возвращается ему же через канал и доставляется один раз."""
    ws = _sock()
    await api.connect(ws, 1, 10)
    await api.broadcast_all("task_created", {"id": 5}, workspace_id=10)
    await _eventually(lambda: ws.send_text.await_count == 1)
    await asyncio.sleep(0.1)
    assert ws.send_text.await_count == 1


async def test_two_api_workers_each_deliver_to_their_own_connections_exactly_once(server, bot):
    w1, w2 = WSManager(), WSManager()
    await w1.start_redis_bridge(_redis(server, decode=False), listen=True)
    await w2.start_redis_bridge(_redis(server, decode=False), listen=True)
    try:
        on_w1, on_w2 = _sock(), _sock()
        await w1.connect(on_w1, 1, 10)
        await w2.connect(on_w2, 2, 10)

        await bot.broadcast_all("chat_message", {"x": 1}, workspace_id=10)

        await _eventually(lambda: on_w1.send_text.await_count == 1 and on_w2.send_text.await_count == 1)
        await asyncio.sleep(0.1)
        assert on_w1.send_text.await_count == 1 and on_w2.send_text.await_count == 1
    finally:
        await w1.stop_redis_bridge()
        await w2.stop_redis_bridge()


async def test_garbage_and_unknown_messages_do_not_kill_the_listener(api, server):
    ws = _sock()
    await api.connect(ws, 1, 10)
    raw = _redis(server, decode=True)
    for junk in ("не json", "{}", json.dumps({"op": "format_disk"}), json.dumps({"op": "users", "user_ids": "x"})):
        await raw.publish(WS_CHANNEL, junk)

    await raw.publish(WS_CHANNEL, json.dumps({"op": "users", "user_ids": [1], "event": "ok", "data": {}}))
    await _eventually(lambda: ws.send_text.await_count == 1)
    assert _events(ws) == [{"event": "ok", "data": {}}]


class _FailingPublish:
    """Redis, у которого publish падает (шина недоступна)."""

    async def publish(self, *a, **k):
        raise ConnectionError("redis down")


async def test_api_falls_back_to_local_delivery_when_publish_fails(api):
    api._redis = _FailingPublish()  # слушатель по-прежнему жив → это процесс API
    ws = _sock()
    await api.connect(ws, 1, 10)
    await api.broadcast_all("task_created", {"id": 1}, workspace_id=10)
    assert ws.send_text.await_count == 1  # доставлено сразу, локально
    assert await api.disconnect_user(1) == 1  # и отключение тоже локальное
    ws.close.assert_awaited_once()


async def test_bot_with_failing_publish_does_not_raise_and_delivers_nothing_locally():
    bot = WSManager()
    bot._redis = _FailingPublish()  # listen=False: слушателя нет
    stray = _sock()
    await bot.connect(stray, 1, 10)  # даже если вдруг есть локальное соединение — не дублируем
    await bot.broadcast_all("chat_message", {}, workspace_id=10)
    await bot.disconnect_user(1)
    stray.send_text.assert_not_awaited()
    stray.close.assert_not_awaited()


async def test_listener_reconnects_after_redis_hiccup(server):
    real = _redis(server, decode=False)

    class Flaky:
        calls = 0

        def pubsub(self):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise ConnectionError("первая подписка не удалась")
            return real.pubsub()

        async def publish(self, *a, **k):
            return await real.publish(*a, **k)

    mgr = WSManager()
    # ready придёт только после успешной подписки (≈1 с backoff) — укладываемся в таймаут старта
    await mgr.start_redis_bridge(Flaky(), listen=True)
    try:
        assert Flaky.calls >= 2
        ws = _sock()
        await mgr.connect(ws, 1, 10)
        await mgr.broadcast_to_users([1], "ok", {})
        await _eventually(lambda: ws.send_text.await_count == 1)
    finally:
        await mgr.stop_redis_bridge()


async def test_stop_bridge_cancels_listener_and_returns_to_local_mode(server):
    mgr = WSManager()
    await mgr.start_redis_bridge(_redis(server, decode=False), listen=True)
    task = mgr._listener
    assert task is not None and not task.done()

    await mgr.stop_redis_bridge()
    assert task.done() and mgr._listener is None and mgr._redis is None

    ws = _sock()
    await mgr.connect(ws, 1, 10)
    await mgr.broadcast_to_users([1], "local", {})  # без шины — локально, как раньше
    assert ws.send_text.await_count == 1


async def test_restart_bridge_does_not_leak_listeners(server):
    mgr = WSManager()
    await mgr.start_redis_bridge(_redis(server, decode=False), listen=True)
    first = mgr._listener
    await mgr.start_redis_bridge(_redis(server, decode=False), listen=True)
    try:
        assert first.done() and mgr._listener is not first
    finally:
        await mgr.stop_redis_bridge()
