from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.repositories.chat_repository import ChatRepository
from src.services import chat_service
from tests.conftest import make_user


class TestDmRepository:
    @pytest.mark.asyncio
    async def test_dm_history_both_directions(self, session):
        a = await make_user(session)
        b = await make_user(session)
        repo = ChatRepository(session)
        await repo.create(a.id, "Привет от A", recipient_id=b.id)
        await repo.create(b.id, "Привет от B", recipient_id=a.id)

        history = await repo.get_dm_history(a.id, b.id, limit=50)

        assert [m.content for m in history] == ["Привет от A", "Привет от B"]

    @pytest.mark.asyncio
    async def test_dm_history_excludes_third_party(self, session):
        a = await make_user(session)
        b = await make_user(session)
        c = await make_user(session)
        repo = ChatRepository(session)
        await repo.create(a.id, "A -> B", recipient_id=b.id)
        await repo.create(a.id, "A -> C", recipient_id=c.id)

        history = await repo.get_dm_history(a.id, b.id, limit=50)

        assert [m.content for m in history] == ["A -> B"]

    @pytest.mark.asyncio
    async def test_dm_messages_excluded_from_general_channel(self, session):
        a = await make_user(session)
        b = await make_user(session)
        repo = ChatRepository(session)
        await repo.create(a.id, "В общий чат")
        await repo.create(a.id, "Личное", recipient_id=b.id)

        general = await repo.get_recent(group_id=None, limit=50)

        assert [m.content for m in general] == ["В общий чат"]

    @pytest.mark.asyncio
    async def test_conversations_list_one_per_partner(self, session):
        a = await make_user(session)
        b = await make_user(session)
        c = await make_user(session)
        repo = ChatRepository(session)
        await repo.create(a.id, "Первое B", recipient_id=b.id)
        await repo.create(b.id, "Ответ B", recipient_id=a.id)
        await repo.create(a.id, "Привет C", recipient_id=c.id)

        conversations = await repo.get_dm_conversations(a.id)
        partner_ids = {m.recipient_id if m.user_id == a.id else m.user_id for m in conversations}

        assert partner_ids == {b.id, c.id}


class TestDmServiceAndBridge:
    @pytest.mark.asyncio
    async def test_send_dm_broadcasts_to_both_participants(self, session):
        a = await make_user(session)
        b = await make_user(session)
        repo = ChatRepository(session)
        service = chat_service.ChatService(repo)

        with patch("src.services.chat_service.ws_manager") as mock_ws:
            mock_ws.broadcast_to_users = AsyncMock()
            with patch("src.services.chat_service.get_bot"):
                message = await service.send_dm(a, b, "Привет!")

            mock_ws.broadcast_to_users.assert_awaited_once()
            call_args = mock_ws.broadcast_to_users.call_args.args
            assert set(call_args[0]) == {a.id, b.id}
            assert call_args[1] == "chat_message"
            assert message.content == "Привет!"

    @pytest.mark.asyncio
    async def test_cannot_message_self(self, session):
        a = await make_user(session)
        repo = ChatRepository(session)
        service = chat_service.ChatService(repo)

        with pytest.raises(Exception):
            await service.send_dm(a, a, "себе")

    @pytest.mark.asyncio
    async def test_dm_mirrors_to_telegram_when_recipient_linked(self, session):
        a = await make_user(session)
        b = await make_user(session)
        b.telegram_id = 555
        await session.commit()
        repo = ChatRepository(session)
        service = chat_service.ChatService(repo)

        with patch("src.services.chat_service.ws_manager") as mock_ws:
            mock_ws.broadcast_to_users = AsyncMock()
            with (
                patch("src.services.chat_service.get_bot") as mock_get_bot,
                patch("src.services.chat_service.remember_reply_target", new=AsyncMock()) as mock_remember,
            ):
                bot = AsyncMock()
                sent_message = MagicMock(message_id=777)
                bot.send_message = AsyncMock(return_value=sent_message)
                mock_get_bot.return_value = bot

                await service.send_dm(a, b, "Привет в телеграм")

                bot.send_message.assert_awaited_once()
                assert bot.send_message.call_args.kwargs["chat_id"] == 555
                mock_remember.assert_awaited_once_with(555, 777, a.id)

    @pytest.mark.asyncio
    async def test_dm_no_mirror_when_recipient_not_linked(self, session):
        a = await make_user(session)
        b = await make_user(session)  # без telegram_id
        repo = ChatRepository(session)
        service = chat_service.ChatService(repo)

        with patch("src.services.chat_service.ws_manager") as mock_ws:
            mock_ws.broadcast_to_users = AsyncMock()
            with patch("src.services.chat_service.get_bot") as mock_get_bot:
                await service.send_dm(a, b, "Без телеграма")
                mock_get_bot.assert_not_called()

    @pytest.mark.asyncio
    async def test_mirror_failure_does_not_raise(self, session):
        a = await make_user(session)
        b = await make_user(session)
        b.telegram_id = 555
        await session.commit()
        repo = ChatRepository(session)
        service = chat_service.ChatService(repo)

        with patch("src.services.chat_service.ws_manager") as mock_ws:
            mock_ws.broadcast_to_users = AsyncMock()
            with patch("src.services.chat_service.get_bot") as mock_get_bot:
                bot = AsyncMock()
                bot.send_message = AsyncMock(side_effect=Exception("Telegram down"))
                mock_get_bot.return_value = bot

                result = await service.send_dm(a, b, "Ещё разок")
                assert result is not None


class TestDmReplyBridge:
    @pytest.mark.asyncio
    async def test_reply_routes_back_to_original_sender(self):
        from src.bot.handlers import dm_bridge

        message = AsyncMock()
        message.chat = MagicMock()
        message.chat.id = 555
        message.chat.type = "private"
        message.from_user = MagicMock()
        message.from_user.id = 555
        message.from_user.is_bot = False
        message.text = "Ответ из телеграма"
        message.reply_to_message = MagicMock()
        message.reply_to_message.message_id = 777

        sender_user = MagicMock(id=2, is_active=True)
        recipient_user = MagicMock(id=1, is_active=True)

        with (
            patch(
                "src.bot.handlers.dm_bridge.get_reply_target",
                new=AsyncMock(return_value=1),
            ),
            patch("src.bot.handlers.dm_bridge.get_session_maker"),
            patch("src.bot.handlers.dm_bridge.UnitOfWork") as MockUow,
            patch.object(dm_bridge, "ChatService") as MockService,
        ):
            uow_instance = AsyncMock()
            uow_instance.__aenter__ = AsyncMock(return_value=uow_instance)
            uow_instance.__aexit__ = AsyncMock(return_value=False)
            uow_instance.users = AsyncMock()
            uow_instance.users.get_by_telegram_id = AsyncMock(return_value=sender_user)
            uow_instance.users.get_user_id = AsyncMock(return_value=recipient_user)
            uow_instance.session = MagicMock()
            MockUow.return_value = uow_instance

            service_instance = MockService.return_value
            service_instance.send_dm = AsyncMock()

            await dm_bridge.handle_dm_reply(message)

            service_instance.send_dm.assert_awaited_once_with(sender_user, recipient_user, "Ответ из телеграма")

    @pytest.mark.asyncio
    async def test_reply_to_unrelated_message_ignored(self):
        from src.bot.handlers import dm_bridge

        message = AsyncMock()
        message.chat = MagicMock()
        message.chat.id = 555
        message.from_user = MagicMock()
        message.from_user.id = 555
        message.from_user.is_bot = False
        message.text = "просто ответ на что-то другое"
        message.reply_to_message = MagicMock()
        message.reply_to_message.message_id = 42

        with (
            patch(
                "src.bot.handlers.dm_bridge.get_reply_target",
                new=AsyncMock(return_value=None),
            ),
            patch.object(dm_bridge, "ChatService") as MockService,
        ):
            await dm_bridge.handle_dm_reply(message)
            MockService.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_own_reply_ignored(self):
        from src.bot.handlers import dm_bridge

        message = AsyncMock()
        message.from_user = MagicMock()
        message.from_user.is_bot = True

        with patch.object(dm_bridge, "ChatService") as MockService:
            await dm_bridge.handle_dm_reply(message)
            MockService.assert_not_called()

    @pytest.mark.asyncio
    async def test_unregistered_replier_ignored(self):
        from src.bot.handlers import dm_bridge

        message = AsyncMock()
        message.chat = MagicMock()
        message.chat.id = 555
        message.from_user = MagicMock()
        message.from_user.id = 555
        message.from_user.is_bot = False
        message.text = "ответ"
        message.reply_to_message = MagicMock()
        message.reply_to_message.message_id = 777

        with (
            patch(
                "src.bot.handlers.dm_bridge.get_reply_target",
                new=AsyncMock(return_value=1),
            ),
            patch("src.bot.handlers.dm_bridge.get_session_maker"),
            patch("src.bot.handlers.dm_bridge.UnitOfWork") as MockUow,
            patch.object(dm_bridge, "ChatService") as MockService,
        ):
            uow_instance = AsyncMock()
            uow_instance.__aenter__ = AsyncMock(return_value=uow_instance)
            uow_instance.__aexit__ = AsyncMock(return_value=False)
            uow_instance.users = AsyncMock()
            uow_instance.users.get_by_telegram_id = AsyncMock(return_value=None)
            MockUow.return_value = uow_instance

            await dm_bridge.handle_dm_reply(message)

            MockService.return_value.send_dm.assert_not_called()


class TestDmEndpointsViaRealApp:
    @pytest.mark.asyncio
    async def test_send_and_read_dm(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="dm_alice", password="pass123")
            bob = await make_user(sess, username="dm_bob", password="pass123")
            bob_id = bob.id

        login = await client.post("/auth/login", json={"username": "dm_alice", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        with patch("src.services.chat_service.get_bot"):
            send_resp = await client.post(
                f"/api/chat/dm/{bob_id}",
                json={"content": "Привет, Боб!"},
                headers=headers,
            )
            assert send_resp.status_code == 200
            assert send_resp.json()["recipient_id"] == bob_id

        history_resp = await client.get(f"/api/chat/dm/{bob_id}", headers=headers)
        assert history_resp.status_code == 200
        contents = [m["content"] for m in history_resp.json()]
        assert "Привет, Боб!" in contents

    @pytest.mark.asyncio
    async def test_third_party_cannot_see_dm(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="dm_alice2", password="pass123")
            bob = await make_user(sess, username="dm_bob2", password="pass123")
            bob_id = bob.id
            await make_user(sess, username="dm_eve", password="pass123")

        alice_login = await client.post("/auth/login", json={"username": "dm_alice2", "password": "pass123"})
        alice_headers = {"Authorization": f"Bearer {alice_login.json()['access_token']}"}
        with patch("src.services.chat_service.get_bot"):
            await client.post(
                f"/api/chat/dm/{bob_id}",
                json={"content": "Секрет"},
                headers=alice_headers,
            )

        eve_login = await client.post("/auth/login", json={"username": "dm_eve", "password": "pass123"})
        eve_headers = {"Authorization": f"Bearer {eve_login.json()['access_token']}"}
        resp = await client.get(f"/api/chat/dm/{bob_id}", headers=eve_headers)

        # Eve видит "свою" (пустую) переписку с Bob, а не чужую с Alice
        contents = [m["content"] for m in resp.json()]
        assert "Секрет" not in contents

    @pytest.mark.asyncio
    async def test_conversations_list_sorted_by_recency(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="dm_alice3", password="pass123")
            bob = await make_user(sess, username="dm_bob3", password="pass123")
            carol = await make_user(sess, username="dm_carol3", password="pass123")
            bob_id, carol_id = bob.id, carol.id

        login = await client.post("/auth/login", json={"username": "dm_alice3", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        with patch("src.services.chat_service.get_bot"):
            await client.post(f"/api/chat/dm/{bob_id}", json={"content": "Первое"}, headers=headers)
            await client.post(f"/api/chat/dm/{carol_id}", json={"content": "Второе"}, headers=headers)

        resp = await client.get("/api/chat/dm/conversations", headers=headers)
        assert resp.status_code == 200
        usernames = [c["username"] for c in resp.json()]
        assert usernames[0] == "dm_carol3"  # самая свежая переписка первая

    @pytest.mark.asyncio
    async def test_cannot_dm_self(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            alice = await make_user(sess, username="dm_alice4", password="pass123")
            alice_id = alice.id

        login = await client.post("/auth/login", json={"username": "dm_alice4", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.post(f"/api/chat/dm/{alice_id}", json={"content": "себе"}, headers=headers)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_dm_to_nonexistent_user_404(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="dm_alice5", password="pass123")

        login = await client.post("/auth/login", json={"username": "dm_alice5", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.post("/api/chat/dm/999999", json={"content": "привет"}, headers=headers)
        assert resp.status_code == 404
