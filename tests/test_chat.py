import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.group import GroupModel
from src.repositories.chat_repository import ChatRepository
from tests.conftest import make_user


async def make_group_with_members(session, member_count=2, author=None):
    group = GroupModel(name=f"group_{uuid.uuid4().hex[:6]}")
    session.add(group)
    await session.commit()
    await session.refresh(group)

    members = []
    for _ in range(member_count):
        user = await make_user(session, username=f"member_{uuid.uuid4().hex[:6]}", password="pass123")
        group.users.append(user)
        members.append(user)

    if author:
        group.users.append(author)

    await session.commit()
    for m in members:
        await session.refresh(m)
    await session.refresh(group)
    return group, members


class TestChatRepository:
    @pytest.mark.asyncio
    async def test_create_and_get_recent_order(self, session):
        user = await make_user(session)
        repo = ChatRepository(session)
        await repo.create(user.id, "Привет")
        await repo.create(user.id, "Как дела?")

        messages = await repo.get_recent(limit=50)

        assert [m.content for m in messages] == ["Привет", "Как дела?"]

    @pytest.mark.asyncio
    async def test_general_and_group_channels_are_isolated(self, session):
        user = await make_user(session)
        group, _ = await make_group_with_members(session, member_count=1, author=user)
        repo = ChatRepository(session)
        await repo.create(user.id, "В общем канале")
        await repo.create(user.id, "В группе", group_id=group.id)

        general = await repo.get_recent(group_id=None, limit=50)
        group_msgs = await repo.get_recent(group_id=group.id, limit=50)

        assert [m.content for m in general] == ["В общем канале"]
        assert [m.content for m in group_msgs] == ["В группе"]

    @pytest.mark.asyncio
    async def test_before_id_cursor_returns_older_only(self, session):
        user = await make_user(session)
        repo = ChatRepository(session)
        m1 = await repo.create(user.id, "Первое")
        await repo.create(user.id, "Второе")
        await repo.create(user.id, "Третье")

        older = await repo.get_recent(before_id=m1.id + 1, limit=50)

        assert [m.content for m in older] == ["Первое"]

    @pytest.mark.asyncio
    async def test_soft_deleted_excluded_from_recent(self, session):
        user = await make_user(session)
        repo = ChatRepository(session)
        m1 = await repo.create(user.id, "Скрою это")
        await repo.create(user.id, "Останется")

        await repo.soft_delete(m1)
        messages = await repo.get_recent(limit=50)

        assert [m.content for m in messages] == ["Останется"]


class TestChatEndpointsViaRealApp:
    @pytest.mark.asyncio
    async def test_send_and_list_general_message(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="chat_user1", password="pass123")

        login = await client.post("/auth/login", json={"username": "chat_user1", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        with patch("src.services.chat_service.ws_manager.broadcast_all", new=AsyncMock()) as broadcast:
            send_resp = await client.post("/api/chat/messages", json={"content": "Привет всем!"}, headers=headers)
            assert send_resp.status_code == 200
            assert send_resp.json()["content"] == "Привет всем!"
            assert send_resp.json()["group_id"] is None
            broadcast.assert_awaited_once()
            assert broadcast.call_args.args[0] == "chat_message"

        list_resp = await client.get("/api/chat/messages", headers=headers)
        contents = [m["content"] for m in list_resp.json()]
        assert "Привет всем!" in contents

    @pytest.mark.asyncio
    async def test_channels_list_includes_general_and_own_groups(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            user = await make_user(sess, username="chat_channels_user", password="pass123")
            group, _ = await make_group_with_members(sess, member_count=1, author=user)

        login = await client.post(
            "/auth/login",
            json={"username": "chat_channels_user", "password": "pass123"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.get("/api/chat/channels", headers=headers)
        assert resp.status_code == 200
        channels = resp.json()
        assert {"group_id": None, "name": "Общий чат"} in channels
        assert any(c["group_id"] == group.id for c in channels)

    @pytest.mark.asyncio
    async def test_group_member_can_send_and_read(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            user = await make_user(sess, username="chat_group_member", password="pass123")
            group, _ = await make_group_with_members(sess, member_count=1, author=user)
            group_id = group.id

        login = await client.post("/auth/login", json={"username": "chat_group_member", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        with patch("src.services.chat_service.ws_manager.broadcast_to_users", new=AsyncMock()) as broadcast:
            send_resp = await client.post(
                "/api/chat/messages",
                json={"content": "Привет группе", "group_id": group_id},
                headers=headers,
            )
            assert send_resp.status_code == 200
            broadcast.assert_awaited_once()

        list_resp = await client.get(f"/api/chat/messages?group_id={group_id}", headers=headers)
        contents = [m["content"] for m in list_resp.json()]
        assert "Привет группе" in contents

    @pytest.mark.asyncio
    async def test_non_member_cannot_read_group_channel(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            owner = await make_user(sess, username="chat_group_owner", password="pass123")
            group, _ = await make_group_with_members(sess, member_count=0, author=owner)
            group_id = group.id
            await make_user(sess, username="chat_outsider", password="pass123")

        login = await client.post("/auth/login", json={"username": "chat_outsider", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.get(f"/api/chat/messages?group_id={group_id}", headers=headers)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_non_member_cannot_send_to_group_channel(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            owner = await make_user(sess, username="chat_group_owner2", password="pass123")
            group, _ = await make_group_with_members(sess, member_count=0, author=owner)
            group_id = group.id
            await make_user(sess, username="chat_outsider2", password="pass123")

        login = await client.post("/auth/login", json={"username": "chat_outsider2", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.post(
            "/api/chat/messages",
            json={"content": "Не должно пройти", "group_id": group_id},
            headers=headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_access_any_group_channel(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            owner = await make_user(sess, username="chat_group_owner3", password="pass123")
            group, _ = await make_group_with_members(sess, member_count=0, author=owner)
            group_id = group.id
            await make_user(sess, username="chat_admin_access", password="pass123", role="admin")

        login = await client.post("/auth/login", json={"username": "chat_admin_access", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.get(f"/api/chat/messages?group_id={group_id}", headers=headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_content_rejected(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="chat_user2", password="pass123")

        login = await client.post("/auth/login", json={"username": "chat_user2", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await client.post("/api/chat/messages", json={"content": ""}, headers=headers)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_own_message_can_be_deleted(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="chat_user3", password="pass123")

        login = await client.post("/auth/login", json={"username": "chat_user3", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        with patch("src.services.chat_service.ws_manager.broadcast_all", new=AsyncMock()):
            send_resp = await client.post("/api/chat/messages", json={"content": "Удалю это"}, headers=headers)
            message_id = send_resp.json()["id"]

            delete_resp = await client.delete(f"/api/chat/messages/{message_id}", headers=headers)
            assert delete_resp.status_code == 204

        list_resp = await client.get("/api/chat/messages", headers=headers)
        contents = [m["content"] for m in list_resp.json()]
        assert "Удалю это" not in contents

    @pytest.mark.asyncio
    async def test_cannot_delete_others_message(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="chat_owner", password="pass123")
            await make_user(sess, username="chat_intruder", password="pass123")

        owner_login = await client.post("/auth/login", json={"username": "chat_owner", "password": "pass123"})
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}

        with patch("src.services.chat_service.ws_manager.broadcast_all", new=AsyncMock()):
            send_resp = await client.post(
                "/api/chat/messages",
                json={"content": "Моё сообщение"},
                headers=owner_headers,
            )
            message_id = send_resp.json()["id"]

            intruder_login = await client.post("/auth/login", json={"username": "chat_intruder", "password": "pass123"})
            intruder_headers = {"Authorization": f"Bearer {intruder_login.json()['access_token']}"}

            resp = await client.delete(f"/api/chat/messages/{message_id}", headers=intruder_headers)
            assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_delete_others_message(self, client, engine):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="chat_owner2", password="pass123")
            await make_user(sess, username="chat_admin", password="pass123", role="admin")

        owner_login = await client.post("/auth/login", json={"username": "chat_owner2", "password": "pass123"})
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}

        with patch("src.services.chat_service.ws_manager.broadcast_all", new=AsyncMock()):
            send_resp = await client.post(
                "/api/chat/messages",
                json={"content": "Сообщение владельца"},
                headers=owner_headers,
            )
            message_id = send_resp.json()["id"]

            admin_login = await client.post("/auth/login", json={"username": "chat_admin", "password": "pass123"})
            admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

            resp = await client.delete(f"/api/chat/messages/{message_id}", headers=admin_headers)
            assert resp.status_code == 204
