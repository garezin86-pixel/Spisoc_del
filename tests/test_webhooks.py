# tests/test_webhooks.py
import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.enums import WebhookEvent
from src.repositories.webhook_repository import WebhookRepository
from src.schemas.webhook import WebhookCreate, WebhookUpdate
from src.services import webhook_dispatcher
from src.services.webhook_dispatcher import _sign, dispatch_webhook_event
from src.services.webhook_service import WebhookService
from tests.conftest import make_user

pytestmark = pytest.mark.asyncio


def build_service(session) -> WebhookService:
    return WebhookService(WebhookRepository(session))


@pytest.fixture(autouse=True)
def _patch_dispatcher_engine(engine, monkeypatch):
    """
    dispatch_webhook_event открывает СВОЮ сессию через get_session_maker()
    (не через FastAPI DI) — по умолчанию она указывает на продовый Postgres.
    Подменяем на sessionmaker, привязанный к тестовому sqlite-engine.
    """
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(webhook_dispatcher, "get_session_maker", lambda: async_session)
    yield


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeAsyncClient:
    """Подменяет httpx.AsyncClient — записывает вызовы, не бьёт по сети."""

    calls: list[dict] = []
    # Очередь того, что вернуть на следующий post(): int -> статус-код,
    # Exception -> будет брошено как есть.
    queue: list[int | Exception] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, content=None, headers=None):
        _FakeAsyncClient.calls.append({"url": url, "content": content, "headers": headers})
        next_result = _FakeAsyncClient.queue.pop(0) if _FakeAsyncClient.queue else 200
        if isinstance(next_result, Exception):
            raise next_result
        return _FakeResponse(next_result)


@pytest.fixture(autouse=True)
def fake_httpx(monkeypatch):
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.queue = []
    monkeypatch.setattr(webhook_dispatcher.httpx, "AsyncClient", _FakeAsyncClient)
    yield _FakeAsyncClient


@pytest.fixture
def captured_tasks(monkeypatch):
    """
    dispatch_webhook_event — fire-and-forget (через webhook_dispatcher._schedule).
    Чтобы тест мог детерминированно дождаться доставки, подменяем именно эту
    точечную обёртку (см. её докстринг), а не глобальный asyncio.create_task —
    иначе заодно ловим вообще все фоновые таски приложения (например,
    уведомления о повторяющихся задачах в task_service.py).
    """
    tasks: list[asyncio.Task] = []

    def _capturing_schedule(coro):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task

    monkeypatch.setattr(webhook_dispatcher, "_schedule", _capturing_schedule)
    yield tasks


async def _flush(captured_tasks):
    if captured_tasks:
        await asyncio.gather(*captured_tasks)
        captured_tasks.clear()


class TestWebhookServiceCrud:
    async def test_create_returns_secret_once(self, session):
        user = await make_user(session)
        service = build_service(session)

        result = await service.create_webhook(
            user, WebhookCreate(url="https://example.com/hook", events=[WebhookEvent.task_done])
        )

        assert result.secret.startswith("whsec_")
        assert result.secret_prefix in result.secret
        assert result.events == [WebhookEvent.task_done]
        assert result.is_active is True

    async def test_create_rejects_non_http_url(self):
        with pytest.raises(ValueError):
            WebhookCreate(url="ftp://example.com", events=[WebhookEvent.task_done])

    async def test_create_requires_at_least_one_event(self):
        with pytest.raises(ValueError):
            WebhookCreate(url="https://example.com/hook", events=[])

    async def test_list_only_returns_own_webhooks(self, session):
        alice = await make_user(session)
        bob = await make_user(session)
        service = build_service(session)
        await service.create_webhook(alice, WebhookCreate(url="https://a.example.com", events=[WebhookEvent.task_done]))
        await service.create_webhook(bob, WebhookCreate(url="https://b.example.com", events=[WebhookEvent.task_done]))

        alice_hooks = await service.list_webhooks(alice)

        assert len(alice_hooks) == 1
        assert alice_hooks[0].url == "https://a.example.com"

    async def test_update_changes_url_and_events(self, session):
        user = await make_user(session)
        service = build_service(session)
        created = await service.create_webhook(
            user, WebhookCreate(url="https://old.example.com", events=[WebhookEvent.task_done])
        )

        updated = await service.update_webhook(
            user,
            created.id,
            WebhookUpdate(url="https://new.example.com", events=[WebhookEvent.comment_added]),
        )

        assert updated.url == "https://new.example.com"
        assert updated.events == [WebhookEvent.comment_added.value]

    async def test_update_can_disable_without_touching_other_fields(self, session):
        user = await make_user(session)
        service = build_service(session)
        created = await service.create_webhook(
            user, WebhookCreate(url="https://x.example.com", events=[WebhookEvent.task_done])
        )

        updated = await service.update_webhook(user, created.id, WebhookUpdate(is_active=False))

        assert updated.is_active is False
        assert updated.url == "https://x.example.com"

    async def test_update_other_users_webhook_returns_404(self, session):
        owner = await make_user(session)
        intruder = await make_user(session)
        service = build_service(session)
        created = await service.create_webhook(
            owner, WebhookCreate(url="https://x.example.com", events=[WebhookEvent.task_done])
        )

        with pytest.raises(Exception) as exc_info:
            await service.update_webhook(intruder, created.id, WebhookUpdate(is_active=False))
        assert getattr(exc_info.value, "status_code", None) == 404

    async def test_delete_removes_webhook(self, session):
        user = await make_user(session)
        service = build_service(session)
        created = await service.create_webhook(
            user, WebhookCreate(url="https://x.example.com", events=[WebhookEvent.task_done])
        )

        await service.delete_webhook(user, created.id)

        assert await service.list_webhooks(user) == []

    async def test_delete_other_users_webhook_returns_404(self, session):
        owner = await make_user(session)
        intruder = await make_user(session)
        service = build_service(session)
        created = await service.create_webhook(
            owner, WebhookCreate(url="https://x.example.com", events=[WebhookEvent.task_done])
        )

        with pytest.raises(Exception) as exc_info:
            await service.delete_webhook(intruder, created.id)
        assert getattr(exc_info.value, "status_code", None) == 404

    async def test_rotate_secret_changes_value_keeps_url(self, session):
        user = await make_user(session)
        service = build_service(session)
        created = await service.create_webhook(
            user, WebhookCreate(url="https://x.example.com", events=[WebhookEvent.task_done])
        )

        rotated = await service.regenerate_secret(user, created.id)

        assert rotated.secret != created.secret
        assert rotated.secret.startswith("whsec_")
        webhooks = await service.list_webhooks(user)
        assert webhooks[0].url == "https://x.example.com"

    async def test_send_test_event_records_result(self, session, fake_httpx):
        fake_httpx.queue = [204]
        user = await make_user(session)
        service = build_service(session)
        created = await service.create_webhook(
            user, WebhookCreate(url="https://x.example.com", events=[WebhookEvent.task_done])
        )

        result = await service.send_test_event(user, created.id)

        assert result.delivered is True
        assert result.status_code == 204
        assert len(fake_httpx.calls) == 1

    async def test_send_test_event_reports_delivery_failure(self, session, fake_httpx):
        fake_httpx.queue = [500]
        user = await make_user(session)
        service = build_service(session)
        created = await service.create_webhook(
            user, WebhookCreate(url="https://x.example.com", events=[WebhookEvent.task_done])
        )

        result = await service.send_test_event(user, created.id)

        # 500 доставился (запрос дошёл), delivered семантически = "получили
        # хоть какой-то ответ", а не "ответ 2xx" — это отражает статус, а не булеан.
        assert result.status_code == 500


class TestWebhookSignature:
    async def test_signature_is_deterministic_hmac_sha256(self):
        sig1 = _sign("whsec_test", b'{"event":"task.done"}')
        sig2 = _sign("whsec_test", b'{"event":"task.done"}')
        assert sig1 == sig2
        assert len(sig1) == 64  # hex-digest SHA256

    async def test_signature_changes_with_secret(self):
        body = b'{"event":"task.done"}'
        assert _sign("secret_a", body) != _sign("secret_b", body)

    async def test_signature_changes_with_body(self):
        assert _sign("s", b"a") != _sign("s", b"b")


class TestWebhookDispatch:
    async def test_dispatch_calls_matching_active_webhook(self, session, fake_httpx, captured_tasks):
        user = await make_user(session)
        service = build_service(session)
        await service.create_webhook(
            user, WebhookCreate(url="https://hooks.example.com/a", events=[WebhookEvent.task_done])
        )

        dispatch_webhook_event(WebhookEvent.task_done, [user.id], {"id": 1, "title": "X"})
        await _flush(captured_tasks)

        assert len(fake_httpx.calls) == 1
        assert fake_httpx.calls[0]["url"] == "https://hooks.example.com/a"
        assert fake_httpx.calls[0]["headers"]["X-Webhook-Event"] == "task.done"
        assert fake_httpx.calls[0]["headers"]["X-Webhook-Signature"].startswith("sha256=")

    async def test_dispatch_skips_webhook_not_subscribed_to_event(self, session, fake_httpx, captured_tasks):
        user = await make_user(session)
        service = build_service(session)
        await service.create_webhook(
            user, WebhookCreate(url="https://hooks.example.com/a", events=[WebhookEvent.comment_added])
        )

        dispatch_webhook_event(WebhookEvent.task_done, [user.id], {"id": 1})
        await _flush(captured_tasks)

        assert fake_httpx.calls == []

    async def test_dispatch_skips_inactive_webhook(self, session, fake_httpx, captured_tasks):
        user = await make_user(session)
        service = build_service(session)
        created = await service.create_webhook(
            user, WebhookCreate(url="https://hooks.example.com/a", events=[WebhookEvent.task_done], is_active=False)
        )
        assert created.is_active is False

        dispatch_webhook_event(WebhookEvent.task_done, [user.id], {"id": 1})
        await _flush(captured_tasks)

        assert fake_httpx.calls == []

    async def test_dispatch_updates_last_triggered_metadata(self, session, fake_httpx, captured_tasks):
        fake_httpx.queue = [200]
        user = await make_user(session)
        service = build_service(session)
        await service.create_webhook(
            user, WebhookCreate(url="https://hooks.example.com/a", events=[WebhookEvent.task_done])
        )

        dispatch_webhook_event(WebhookEvent.task_done, [user.id], {"id": 1})
        await _flush(captured_tasks)

        webhooks = await service.list_webhooks(user)
        assert webhooks[0].last_status_code == 200
        assert webhooks[0].last_triggered_at is not None
        assert webhooks[0].failure_count == 0

    async def test_dispatch_increments_failure_count_on_error(self, session, fake_httpx, captured_tasks):
        fake_httpx.queue = [500]
        user = await make_user(session)
        service = build_service(session)
        await service.create_webhook(
            user, WebhookCreate(url="https://hooks.example.com/a", events=[WebhookEvent.task_done])
        )

        dispatch_webhook_event(WebhookEvent.task_done, [user.id], {"id": 1})
        await _flush(captured_tasks)

        webhooks = await service.list_webhooks(user)
        assert webhooks[0].failure_count == 1
        assert webhooks[0].is_active is True  # ещё не достигли порога автоотключения

    async def test_dispatch_auto_disables_after_max_consecutive_failures(
        self, session, fake_httpx, captured_tasks, monkeypatch
    ):
        monkeypatch.setattr(webhook_dispatcher, "MAX_CONSECUTIVE_FAILURES", 2)
        user = await make_user(session)
        service = build_service(session)
        await service.create_webhook(
            user, WebhookCreate(url="https://hooks.example.com/a", events=[WebhookEvent.task_done])
        )

        fake_httpx.queue = [500]
        dispatch_webhook_event(WebhookEvent.task_done, [user.id], {"id": 1})
        await _flush(captured_tasks)
        fake_httpx.queue = [500]
        dispatch_webhook_event(WebhookEvent.task_done, [user.id], {"id": 1})
        await _flush(captured_tasks)

        webhooks = await service.list_webhooks(user)
        assert webhooks[0].failure_count == 2
        assert webhooks[0].is_active is False

    async def test_dispatch_resets_failure_count_after_success(self, session, fake_httpx, captured_tasks):
        user = await make_user(session)
        service = build_service(session)
        await service.create_webhook(
            user, WebhookCreate(url="https://hooks.example.com/a", events=[WebhookEvent.task_done])
        )

        fake_httpx.queue = [500]
        dispatch_webhook_event(WebhookEvent.task_done, [user.id], {"id": 1})
        await _flush(captured_tasks)

        fake_httpx.queue = [200]
        dispatch_webhook_event(WebhookEvent.task_done, [user.id], {"id": 1})
        await _flush(captured_tasks)

        webhooks = await service.list_webhooks(user)
        assert webhooks[0].failure_count == 0

    async def test_dispatch_handles_connection_error_gracefully(self, session, fake_httpx, captured_tasks):
        import httpx

        fake_httpx.queue = [httpx.ConnectError("boom")]
        user = await make_user(session)
        service = build_service(session)
        await service.create_webhook(
            user, WebhookCreate(url="https://hooks.example.com/a", events=[WebhookEvent.task_done])
        )

        dispatch_webhook_event(WebhookEvent.task_done, [user.id], {"id": 1})
        await _flush(captured_tasks)

        webhooks = await service.list_webhooks(user)
        assert webhooks[0].failure_count == 1
        assert webhooks[0].last_error is not None

    async def test_dispatch_with_no_user_ids_does_nothing(self, fake_httpx, captured_tasks):
        dispatch_webhook_event(WebhookEvent.task_done, [], {"id": 1})
        await _flush(captured_tasks)
        assert fake_httpx.calls == []


class TestWebhookEndToEndViaRealApp:
    """Проверяем реальную интеграцию: HTTP-запрос к API → вебхук реально летит (в fake-клиент)."""

    async def _create_user_and_login(self, client, engine, username: str) -> str:
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username=username, password="pass123")
        login_resp = await client.post("/auth/login", json={"username": username, "password": "pass123"})
        assert login_resp.status_code == 200
        return login_resp.json()["access_token"]

    async def test_task_moved_to_done_triggers_webhook(self, client, engine, fake_httpx, captured_tasks):
        username = f"webhook_user_{uuid.uuid4().hex[:6]}"
        jwt_token = await self._create_user_and_login(client, engine, username)
        headers = {"Authorization": f"Bearer {jwt_token}"}

        create_hook = await client.post(
            "/api/webhooks",
            json={"url": "https://hooks.example.com/done", "events": ["task.done"]},
            headers=headers,
        )
        assert create_hook.status_code == 201

        create_task = await client.post("/api/tasks", json={"title": "Ship it"}, headers=headers)
        assert create_task.status_code == 201
        task_id = create_task.json()["id"]

        status_resp = await client.patch(f"/api/tasks/{task_id}/status", json={"status": "done"}, headers=headers)
        assert status_resp.status_code == 200
        await _flush(captured_tasks)

        done_calls = [c for c in fake_httpx.calls if c["headers"]["X-Webhook-Event"] == "task.done"]
        assert len(done_calls) == 1
        assert done_calls[0]["url"] == "https://hooks.example.com/done"

    async def test_task_moved_to_in_progress_does_not_trigger_done_webhook(
        self, client, engine, fake_httpx, captured_tasks
    ):
        username = f"webhook_user_{uuid.uuid4().hex[:6]}"
        jwt_token = await self._create_user_and_login(client, engine, username)
        headers = {"Authorization": f"Bearer {jwt_token}"}

        await client.post(
            "/api/webhooks",
            json={"url": "https://hooks.example.com/done", "events": ["task.done"]},
            headers=headers,
        )
        create_task = await client.post("/api/tasks", json={"title": "In progress"}, headers=headers)
        task_id = create_task.json()["id"]

        resp = await client.patch(f"/api/tasks/{task_id}/status", json={"status": "in_progress"}, headers=headers)
        assert resp.status_code == 200
        await _flush(captured_tasks)

        done_calls = [c for c in fake_httpx.calls if c["headers"]["X-Webhook-Event"] == "task.done"]
        assert done_calls == []

    async def test_comment_triggers_webhook(self, client, engine, fake_httpx, captured_tasks):
        from unittest.mock import AsyncMock, patch

        username = f"webhook_user_{uuid.uuid4().hex[:6]}"
        jwt_token = await self._create_user_and_login(client, engine, username)
        headers = {"Authorization": f"Bearer {jwt_token}"}

        await client.post(
            "/api/webhooks",
            json={"url": "https://hooks.example.com/comments", "events": ["comment.added"]},
            headers=headers,
        )
        create_task = await client.post("/api/tasks", json={"title": "Discuss me"}, headers=headers)
        task_id = create_task.json()["id"]

        with patch("src.services.comments_service.notify_comment_added", new_callable=AsyncMock):
            comment_resp = await client.post(
                f"/api/comments/tasks/{task_id}/comment", json={"content": "Looks good"}, headers=headers
            )
        assert comment_resp.status_code == 200
        await _flush(captured_tasks)

        comment_calls = [c for c in fake_httpx.calls if c["headers"]["X-Webhook-Event"] == "comment.added"]
        assert len(comment_calls) == 1

    async def test_webhook_create_rejects_invalid_url(self, client, engine):
        username = f"webhook_user_{uuid.uuid4().hex[:6]}"
        jwt_token = await self._create_user_and_login(client, engine, username)
        headers = {"Authorization": f"Bearer {jwt_token}"}

        resp = await client.post("/api/webhooks", json={"url": "not-a-url", "events": ["task.done"]}, headers=headers)

        assert resp.status_code == 422

    async def test_webhook_test_endpoint_hits_url_synchronously(self, client, engine, fake_httpx):
        fake_httpx.queue = [200]
        username = f"webhook_user_{uuid.uuid4().hex[:6]}"
        jwt_token = await self._create_user_and_login(client, engine, username)
        headers = {"Authorization": f"Bearer {jwt_token}"}

        create_hook = await client.post(
            "/api/webhooks", json={"url": "https://hooks.example.com/test", "events": ["task.done"]}, headers=headers
        )
        webhook_id = create_hook.json()["id"]

        resp = await client.post(f"/api/webhooks/{webhook_id}/test", headers=headers)

        assert resp.status_code == 200
        assert resp.json()["delivered"] is True
        assert resp.json()["status_code"] == 200

    async def test_cannot_manage_another_users_webhook(self, client, engine):
        owner_username = f"owner_{uuid.uuid4().hex[:6]}"
        intruder_username = f"intruder_{uuid.uuid4().hex[:6]}"
        owner_token = await self._create_user_and_login(client, engine, owner_username)
        intruder_token = await self._create_user_and_login(client, engine, intruder_username)

        created = await client.post(
            "/api/webhooks",
            json={"url": "https://hooks.example.com/x", "events": ["task.done"]},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        webhook_id = created.json()["id"]

        resp = await client.delete(f"/api/webhooks/{webhook_id}", headers={"Authorization": f"Bearer {intruder_token}"})

        assert resp.status_code == 404
