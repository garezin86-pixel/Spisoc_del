# tests/test_push_service.py
import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.repositories.push_repository import PushRepository
from src.schemas.push_subscription import PushSubscriptionCreate, PushSubscriptionKeys
from src.services.push_service import PushService, send_push_to_user
from tests.conftest import make_user


def build_service(session):
    return PushService(PushRepository(session))


def make_subscription_data(endpoint=None):
    return PushSubscriptionCreate(
        endpoint=endpoint or f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4().hex}",
        keys=PushSubscriptionKeys(p256dh="fake-p256dh-key", auth="fake-auth-key"),
    )


class TestSubscribe:
    @pytest.mark.asyncio
    async def test_creates_subscription(self, session):
        user = await make_user(session)
        service = build_service(session)

        result = await service.subscribe(user, make_subscription_data())

        assert result.user_id == user.id

    @pytest.mark.asyncio
    async def test_resubscribing_same_endpoint_updates_not_duplicates(self, session):
        user = await make_user(session)
        service = build_service(session)
        endpoint = f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4().hex}"

        await service.subscribe(user, make_subscription_data(endpoint))
        await service.subscribe(user, make_subscription_data(endpoint))

        subs = await service.list_subscriptions(user)
        assert len(subs) == 1

    @pytest.mark.asyncio
    async def test_multiple_devices_for_same_user(self, session):
        user = await make_user(session)
        service = build_service(session)

        await service.subscribe(user, make_subscription_data())
        await service.subscribe(user, make_subscription_data())

        subs = await service.list_subscriptions(user)
        assert len(subs) == 2


class TestUnsubscribe:
    @pytest.mark.asyncio
    async def test_removes_subscription(self, session):
        user = await make_user(session)
        service = build_service(session)
        data = make_subscription_data()
        await service.subscribe(user, data)

        await service.unsubscribe(user, data.endpoint)

        subs = await service.list_subscriptions(user)
        assert subs == []

    @pytest.mark.asyncio
    async def test_unsubscribing_nonexistent_endpoint_is_idempotent(self, session):
        user = await make_user(session)
        service = build_service(session)

        result = await service.unsubscribe(user, "https://does-not-exist.example.com/x")

        assert result == {"message": "unsubscribed"}

    @pytest.mark.asyncio
    async def test_cannot_unsubscribe_someone_elses_subscription(self, session):
        owner = await make_user(session, username=f"owner_{uuid.uuid4().hex[:6]}", password="pass123")
        stranger = await make_user(session, username=f"stranger_{uuid.uuid4().hex[:6]}", password="pass123")
        service = build_service(session)
        data = make_subscription_data()
        await service.subscribe(owner, data)

        await service.unsubscribe(stranger, data.endpoint)

        subs = await service.list_subscriptions(owner)
        assert len(subs) == 1


class TestSendPushToUser:
    @pytest.mark.asyncio
    async def test_no_vapid_key_returns_zero(self, session):
        user = await make_user(session)
        repo = PushRepository(session)
        await repo.create_or_update(user.id, "https://x.example.com/1", "p", "a")

        with patch("src.services.push_service.VAPID_PRIVATE_KEY", ""):
            sent = await send_push_to_user(repo, user.id, "Заголовок", "Текст")

        assert sent == 0

    @pytest.mark.asyncio
    async def test_no_subscriptions_returns_zero(self, session):
        user = await make_user(session)
        repo = PushRepository(session)

        with patch("src.services.push_service.VAPID_PRIVATE_KEY", "fake-key"):
            sent = await send_push_to_user(repo, user.id, "Заголовок", "Текст")

        assert sent == 0

    @pytest.mark.asyncio
    async def test_successful_send_counted(self, session):
        user = await make_user(session)
        repo = PushRepository(session)
        await repo.create_or_update(user.id, "https://x.example.com/1", "p", "a")

        with (
            patch("src.services.push_service.VAPID_PRIVATE_KEY", "fake-key"),
            patch("src.services.push_service._send_push_sync", return_value=None) as mock_send,
        ):
            sent = await send_push_to_user(repo, user.id, "Заголовок", "Текст тела")

        assert sent == 1
        mock_send.assert_called_once()
        payload = mock_send.call_args.args[1]
        assert payload["title"] == "Заголовок"
        assert payload["body"] == "Текст тела"

    @pytest.mark.asyncio
    async def test_sends_to_all_user_devices(self, session):
        user = await make_user(session)
        repo = PushRepository(session)
        await repo.create_or_update(user.id, "https://x.example.com/1", "p1", "a1")
        await repo.create_or_update(user.id, "https://x.example.com/2", "p2", "a2")

        with (
            patch("src.services.push_service.VAPID_PRIVATE_KEY", "fake-key"),
            patch("src.services.push_service._send_push_sync", return_value=None) as mock_send,
        ):
            sent = await send_push_to_user(repo, user.id, "T", "B")

        assert sent == 2
        assert mock_send.call_count == 2

    @pytest.mark.asyncio
    async def test_expired_subscription_auto_removed_on_410(self, session):
        from pywebpush import WebPushException

        user = await make_user(session)
        repo = PushRepository(session)
        await repo.create_or_update(user.id, "https://x.example.com/1", "p", "a")

        fake_response = MagicMock(status_code=410)
        exc = WebPushException("Gone", response=fake_response)

        with (
            patch("src.services.push_service.VAPID_PRIVATE_KEY", "fake-key"),
            patch("src.services.push_service._send_push_sync", side_effect=exc),
        ):
            sent = await send_push_to_user(repo, user.id, "T", "B")

        assert sent == 0
        remaining = await repo.list_for_user(user.id)
        assert remaining == []

    @pytest.mark.asyncio
    async def test_expired_subscription_auto_removed_on_404(self, session):
        from pywebpush import WebPushException

        user = await make_user(session)
        repo = PushRepository(session)
        await repo.create_or_update(user.id, "https://x.example.com/1", "p", "a")

        fake_response = MagicMock(status_code=404)
        exc = WebPushException("Not Found", response=fake_response)

        with (
            patch("src.services.push_service.VAPID_PRIVATE_KEY", "fake-key"),
            patch("src.services.push_service._send_push_sync", side_effect=exc),
        ):
            await send_push_to_user(repo, user.id, "T", "B")

        remaining = await repo.list_for_user(user.id)
        assert remaining == []

    @pytest.mark.asyncio
    async def test_other_errors_do_not_delete_subscription(self, session):
        """Временная ошибка (не 404/410) НЕ должна удалять подписку — она может ещё сработать в следующий раз."""
        from pywebpush import WebPushException

        user = await make_user(session)
        repo = PushRepository(session)
        await repo.create_or_update(user.id, "https://x.example.com/1", "p", "a")

        fake_response = MagicMock(status_code=500)
        exc = WebPushException("Server Error", response=fake_response)

        with (
            patch("src.services.push_service.VAPID_PRIVATE_KEY", "fake-key"),
            patch("src.services.push_service._send_push_sync", side_effect=exc),
        ):
            sent = await send_push_to_user(repo, user.id, "T", "B")

        assert sent == 0
        remaining = await repo.list_for_user(user.id)
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_one_device_failing_does_not_block_others(self, session):
        user = await make_user(session)
        repo = PushRepository(session)
        await repo.create_or_update(user.id, "https://x.example.com/1", "p1", "a1")
        await repo.create_or_update(user.id, "https://x.example.com/2", "p2", "a2")

        call_count = {"n": 0}

        def flaky_send(subscription_info, payload):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("Временная сетевая ошибка")
            return None

        with (
            patch("src.services.push_service.VAPID_PRIVATE_KEY", "fake-key"),
            patch("src.services.push_service._send_push_sync", side_effect=flaky_send),
        ):
            sent = await send_push_to_user(repo, user.id, "T", "B")

        assert sent == 1  # второе устройство успешно получило push


class TestVapidKeyParsing:
    """
    Регрессионный тест на реальный баг: pywebpush.webpush(), получив
    vapid_private_key строкой (не объектом Vapid), сам вызывает
    Vapid.from_string() — а тот ожидает base64url raw/DER, а НЕ PEM.
    Настоящий PEM (с "-----BEGIN/END PRIVATE KEY-----") ломается на
    from_string() с "ASN.1 parsing error: invalid length". Наш _get_vapid()
    должен использовать Vapid.from_pem(), который парсит PEM корректно.
    """

    @pytest.mark.asyncio
    async def test_real_pem_key_is_parsed_correctly(self, session):
        from py_vapid import Vapid

        from src.services import push_service

        # Генерируем настоящую пару ключей — не фейковую строку
        real_vapid = Vapid()
        real_vapid.generate_keys()
        real_pem = real_vapid.private_pem().decode()

        # Сбрасываем кэш синглтона перед тестом
        push_service._vapid_instance = None
        try:
            with patch("src.services.push_service.VAPID_PRIVATE_KEY", real_pem):
                vapid_obj = push_service._get_vapid()
                assert vapid_obj.private_key is not None
        finally:
            push_service._vapid_instance = None

    @pytest.mark.asyncio
    async def test_get_vapid_caches_instance(self, session):
        from py_vapid import Vapid

        from src.services import push_service

        real_vapid = Vapid()
        real_vapid.generate_keys()
        real_pem = real_vapid.private_pem().decode()

        push_service._vapid_instance = None
        try:
            with patch("src.services.push_service.VAPID_PRIVATE_KEY", real_pem):
                first = push_service._get_vapid()
                second = push_service._get_vapid()
                assert first is second
        finally:
            push_service._vapid_instance = None

    @pytest.mark.asyncio
    async def test_missing_vapid_key_raises_runtime_error(self, session):
        from src.services import push_service

        push_service._vapid_instance = None
        try:
            with patch("src.services.push_service.VAPID_PRIVATE_KEY", ""):
                with pytest.raises(RuntimeError, match="VAPID_PRIVATE_KEY"):
                    push_service._get_vapid()
        finally:
            push_service._vapid_instance = None
