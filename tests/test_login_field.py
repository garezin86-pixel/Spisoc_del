# tests/test_login_field.py
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.repositories.users_repository import UserRepository
from src.services.user_service import UserService
from src.utils.login_generator import build_login_base, generate_temp_password
from tests.conftest import make_user

pytestmark = pytest.mark.asyncio


class TestBuildLoginBase:
    async def test_two_word_fio_uses_surname_and_initial(self):
        assert build_login_base("Иванов Иван") == "ivanov.i"

    async def test_three_word_fio_ignores_patronymic(self):
        assert build_login_base("Иванов Иван Иванович") == "ivanov.i"

    async def test_single_word_uses_surname_only(self):
        assert build_login_base("Ким") == "kim"

    async def test_yo_transliterated_as_e(self):
        assert build_login_base("Пётр Ёлкин") == "petr.e"

    async def test_empty_string_falls_back_to_user(self):
        assert build_login_base("   ") == "user"

    async def test_non_transliterable_falls_back_to_user(self):
        assert build_login_base("😀 😀") == "user"

    async def test_latin_fio_passthrough(self):
        assert build_login_base("Smith John") == "smith.j"

    async def test_result_is_lowercase_ascii_only(self):
        result = build_login_base("Щукин Юрий Ъь")
        assert result == result.lower()
        assert all(ord(c) < 128 for c in result)


class TestGenerateTempPassword:
    async def test_default_length_is_twelve(self):
        assert len(generate_temp_password()) == 12

    async def test_custom_length_respected(self):
        assert len(generate_temp_password(20)) == 20

    async def test_excludes_ambiguous_characters(self):
        password = generate_temp_password(500)  # длинный, чтобы почти наверняка задеть весь алфавит
        assert not any(c in password for c in "0O1lI")

    async def test_two_calls_differ(self):
        assert generate_temp_password() != generate_temp_password()


class TestLoginBasedAuth:
    async def test_user_can_log_in_via_login_field(self, session):
        user = await make_user(session, username="Иванов Иван Иванович", password="pass123")
        user.login = "ivanov.i"
        await session.commit()
        repo = UserRepository(session)

        found = await repo.get_by_login("ivanov.i")

        assert found is not None
        assert found.id == user.id

    async def test_get_by_login_returns_none_for_unknown(self, session):
        repo = UserRepository(session)
        assert await repo.get_by_login("nobody.x") is None

    async def test_old_user_without_login_still_found_by_username(self, session):
        """Обратная совместимость: у пользователей без login поиск должен идти по username."""
        user = await make_user(session, username="legacy_user", password="pass123")
        repo = UserRepository(session)

        assert await repo.get_by_login("legacy_user") is None
        found = await repo.get_by_username("legacy_user")
        assert found is not None and found.id == user.id


class TestChangePassword:
    def build_service(self, session) -> UserService:
        return UserService(UserRepository(session))

    async def test_change_password_with_correct_current_password(self, session):
        user = await make_user(session, password="old-pass-123")
        service = self.build_service(session)

        await service.change_password(user, "old-pass-123", "new-pass-456")

        from src.core.security import verify_password

        assert verify_password("new-pass-456", user.password_hash)

    async def test_change_password_clears_must_change_flag(self, session):
        user = await make_user(session, password="old-pass-123")
        user.must_change_password = True
        await session.commit()
        service = self.build_service(session)

        await service.change_password(user, "old-pass-123", "new-pass-456")

        assert user.must_change_password is False

    async def test_change_password_rejects_wrong_current_password(self, session):
        user = await make_user(session, password="old-pass-123")
        service = self.build_service(session)

        with pytest.raises(Exception) as exc_info:
            await service.change_password(user, "totally-wrong", "new-pass-456")
        assert getattr(exc_info.value, "status_code", None) == 401


class TestLoginEndToEndViaRealApp:
    async def _create_user_with_login(self, engine, username, login, password="pass123", must_change=False):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            user = await make_user(sess, username=username, password=password)
            user.login = login
            user.must_change_password = must_change
            await sess.commit()
            return user.id

    async def test_login_via_login_field_returns_tokens(self, client, engine):
        suffix = uuid.uuid4().hex[:6]
        await self._create_user_with_login(engine, f"Иванов Иван {suffix}", f"ivanov.i.{suffix}")

        resp = await client.post("/auth/login", json={"username": f"ivanov.i.{suffix}", "password": "pass123"})

        assert resp.status_code == 200
        assert resp.json()["access_token"] is not None

    async def test_login_still_works_via_username_when_no_login_set(self, client, engine):
        username = f"plain_user_{uuid.uuid4().hex[:6]}"
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username=username, password="pass123")

        resp = await client.post("/auth/login", json={"username": username, "password": "pass123"})

        assert resp.status_code == 200
        assert resp.json()["access_token"] is not None

    async def test_login_reports_must_change_password_flag(self, client, engine):
        suffix = uuid.uuid4().hex[:6]
        await self._create_user_with_login(engine, f"Temp User {suffix}", f"temp.u.{suffix}", must_change=True)

        resp = await client.post("/auth/login", json={"username": f"temp.u.{suffix}", "password": "pass123"})

        assert resp.json()["must_change_password"] is True

    async def test_change_password_via_http(self, client, engine):
        suffix = uuid.uuid4().hex[:6]
        await self._create_user_with_login(engine, f"Change Me {suffix}", f"change.m.{suffix}")
        login_resp = await client.post("/auth/login", json={"username": f"change.m.{suffix}", "password": "pass123"})
        headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        resp = await client.post(
            "/api/users/me/password",
            json={"current_password": "pass123", "new_password": "brand-new-pass"},
            headers=headers,
        )
        assert resp.status_code == 204

        old_login = await client.post("/auth/login", json={"username": f"change.m.{suffix}", "password": "pass123"})
        assert old_login.status_code == 401

        new_login = await client.post(
            "/auth/login", json={"username": f"change.m.{suffix}", "password": "brand-new-pass"}
        )
        assert new_login.status_code == 200

    async def test_change_password_requires_auth(self, client):
        resp = await client.post("/api/users/me/password", json={"current_password": "x", "new_password": "y" * 6})
        assert resp.status_code in (401, 403)


class TestMentionByLoginField:
    async def test_mention_matches_by_login_not_only_username(self, session, engine):
        from unittest.mock import AsyncMock, patch

        from src.models.comment import CommentModel
        from src.services.notifications import notify_comment_added
        from tests.test_notifications import create_notification_settings, create_task_with_users, unique_tg_id

        task, author, executor = await create_task_with_users(session)
        bystander = await make_user(session, username="Сидоров Пётр Ильич", password="pass123")
        bystander.login = "sidorov.p"
        bystander.telegram_id = unique_tg_id()
        await session.commit()
        await session.refresh(bystander)
        await create_notification_settings(session, bystander.id)

        commenter = await make_user(session, username=f"comm_{uuid.uuid4().hex[:6]}", password="pass123")
        comment = CommentModel(content="гляньте @sidorov.p, пожалуйста", task_id=task.id, user_id=commenter.id)
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        test_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        with (
            patch("src.services.notifications.get_bot") as mock_get_bot,
            patch("src.services.notifications.get_session_maker", return_value=test_session_maker),
        ):
            bot = AsyncMock()
            mock_get_bot.return_value = bot

            await notify_comment_added(comment.id)

            sent_to = {c.kwargs["chat_id"] for c in bot.send_message.call_args_list}
            assert bystander.telegram_id in sent_to
