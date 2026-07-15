# tests/test_personal_access_tokens.py
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from src.models.personal_access_token import PersonalAccessTokenModel
from src.repositories.pat_repository import PatRepository
from src.schemas.personal_access_token import PersonalAccessTokenCreate
from src.services.pat_service import TOKEN_PREFIX, PatService, authenticate_by_pat
from tests.conftest import make_user


def build_service(session):
    return PatService(PatRepository(session))


class TestCreateToken:
    @pytest.mark.asyncio
    async def test_creates_token_with_pat_prefix(self, session):
        user = await make_user(session)
        service = build_service(session)

        result = await service.create_token(user, PersonalAccessTokenCreate(name="Zapier"))

        assert result.token.startswith(TOKEN_PREFIX)
        assert result.name == "Zapier"

    @pytest.mark.asyncio
    async def test_full_token_only_returned_once(self, session):
        """Токен возвращается в ответе на создание, но не хранится в открытом виде в БД."""
        user = await make_user(session)
        service = build_service(session)

        result = await service.create_token(user, PersonalAccessTokenCreate(name="X"))

        repo = PatRepository(session)
        stored = await repo.get_by_id(result.id)
        assert stored.token_hash != result.token
        assert result.token not in stored.token_hash

    @pytest.mark.asyncio
    async def test_token_prefix_stored_for_display(self, session):
        user = await make_user(session)
        service = build_service(session)

        result = await service.create_token(user, PersonalAccessTokenCreate(name="X"))

        assert result.token.startswith(result.token_prefix)

    @pytest.mark.asyncio
    async def test_no_expiry_by_default(self, session):
        user = await make_user(session)
        service = build_service(session)

        result = await service.create_token(user, PersonalAccessTokenCreate(name="Бессрочный"))

        assert result.expires_at is None

    @pytest.mark.asyncio
    async def test_expires_in_days_sets_expiry(self, session):
        user = await make_user(session)
        service = build_service(session)

        result = await service.create_token(user, PersonalAccessTokenCreate(name="Временный", expires_in_days=7))

        assert result.expires_at is not None
        delta = result.expires_at.replace(tzinfo=None) - datetime.now(timezone.utc).replace(tzinfo=None)
        assert timedelta(days=6) < delta < timedelta(days=8)

    @pytest.mark.asyncio
    async def test_two_tokens_for_same_user_have_different_values(self, session):
        user = await make_user(session)
        service = build_service(session)

        t1 = await service.create_token(user, PersonalAccessTokenCreate(name="A"))
        t2 = await service.create_token(user, PersonalAccessTokenCreate(name="B"))

        assert t1.token != t2.token


class TestListTokens:
    @pytest.mark.asyncio
    async def test_returns_only_own_tokens(self, session):
        user1 = await make_user(session, username=f"u1_{uuid.uuid4().hex[:6]}", password="pass123")
        user2 = await make_user(session, username=f"u2_{uuid.uuid4().hex[:6]}", password="pass123")
        service = build_service(session)
        await service.create_token(user1, PersonalAccessTokenCreate(name="Токен U1"))
        await service.create_token(user2, PersonalAccessTokenCreate(name="Токен U2"))

        tokens = await service.list_tokens(user1)

        assert len(tokens) == 1
        assert tokens[0].name == "Токен U1"

    @pytest.mark.asyncio
    async def test_does_not_expose_full_token_or_hash_in_listing_schema(self, session):
        """Схема PersonalAccessTokenSchema не содержит ни token, ни token_hash полей."""
        from src.schemas.personal_access_token import PersonalAccessTokenSchema

        assert "token" not in PersonalAccessTokenSchema.model_fields
        assert "token_hash" not in PersonalAccessTokenSchema.model_fields


class TestRevokeToken:
    @pytest.mark.asyncio
    async def test_owner_can_revoke(self, session):
        user = await make_user(session)
        service = build_service(session)
        created = await service.create_token(user, PersonalAccessTokenCreate(name="X"))

        await service.revoke_token(user, created.id)

        tokens = await service.list_tokens(user)
        assert tokens == []

    @pytest.mark.asyncio
    async def test_revoked_token_no_longer_authenticates(self, session):
        user = await make_user(session)
        service = build_service(session)
        created = await service.create_token(user, PersonalAccessTokenCreate(name="X"))

        await service.revoke_token(user, created.id)

        authenticated = await authenticate_by_pat(session, created.token)
        assert authenticated is None

    @pytest.mark.asyncio
    async def test_other_user_cannot_revoke_returns_404_not_403(self, session):
        """404, не 403 — чтобы не подтверждать существование чужого id токена перебором."""
        owner = await make_user(session, username=f"owner_{uuid.uuid4().hex[:6]}", password="pass123")
        stranger = await make_user(session, username=f"stranger_{uuid.uuid4().hex[:6]}", password="pass123")
        service = build_service(session)
        created = await service.create_token(owner, PersonalAccessTokenCreate(name="X"))

        with pytest.raises(HTTPException) as exc:
            await service.revoke_token(stranger, created.id)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_nonexistent_token_returns_404(self, session):
        user = await make_user(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.revoke_token(user, 999999)

        assert exc.value.status_code == 404


class TestAuthenticateByPat:
    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self, session):
        user = await make_user(session)
        service = build_service(session)
        created = await service.create_token(user, PersonalAccessTokenCreate(name="X"))

        authenticated = await authenticate_by_pat(session, created.token)

        assert authenticated is not None
        assert authenticated.id == user.id

    @pytest.mark.asyncio
    async def test_garbage_token_returns_none(self, session):
        result = await authenticate_by_pat(session, "pat_totally-made-up-value")
        assert result is None

    @pytest.mark.asyncio
    async def test_non_pat_prefixed_token_returns_none_immediately(self, session):
        """Не пытается лезть в БД за обычным JWT — сразу отсекает по префиксу."""
        result = await authenticate_by_pat(session, "eyJhbGciOiJIUzI1NiJ9.some.jwt")
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_token_returns_none(self, session):
        user = await make_user(session)
        repo = PatRepository(session)
        # Создаём токен с уже прошедшим сроком напрямую через репозиторий,
        # чтобы не ждать реального времени
        raw_token = "pat_expired-test-token-value"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        await repo.create(
            user_id=user.id,
            name="Просроченный",
            token_hash=token_hash,
            token_prefix=raw_token[:12],
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )

        result = await authenticate_by_pat(session, raw_token)

        assert result is None

    @pytest.mark.asyncio
    async def test_inactive_user_token_returns_none(self, session):
        user = await make_user(session)
        service = build_service(session)
        created = await service.create_token(user, PersonalAccessTokenCreate(name="X"))
        user.is_active = False
        await session.commit()

        result = await authenticate_by_pat(session, created.token)

        assert result is None

    @pytest.mark.asyncio
    async def test_updates_last_used_at(self, session):
        user = await make_user(session)
        service = build_service(session)
        created = await service.create_token(user, PersonalAccessTokenCreate(name="X"))

        repo = PatRepository(session)
        before = await repo.get_by_id(created.id)
        assert before.last_used_at is None

        await authenticate_by_pat(session, created.token)

        after = await repo.get_by_id(created.id)
        assert after.last_used_at is not None

    @pytest.mark.asyncio
    async def test_deleting_user_cascades_to_tokens(self, session):
        """ondelete=CASCADE / cascade delete-orphan — токены не должны сиротеть при удалении пользователя."""
        user = await make_user(session)
        service = build_service(session)
        await service.create_token(user, PersonalAccessTokenCreate(name="X"))

        from sqlalchemy import select

        # Загружаем пользователя со связью, чтобы ORM-каскад сработал (см. аналогичный
        # комментарий в test_checklist_service.py про cascade + lazy loading)
        result = await session.execute(select(type(user)).where(type(user).id == user.id))
        loaded_user = result.scalar_one()
        await session.refresh(loaded_user, ["personal_access_tokens"])
        await session.delete(loaded_user)
        await session.commit()

        remaining = await session.execute(select(PersonalAccessTokenModel))
        assert remaining.scalars().all() == []


class TestPatEndToEndViaRealApp:
    """
    В отличие от остальных тестов файла (напрямую через сервис), здесь —
    полный путь через настоящий HTTP-стек: Authorization: Bearer pat_...
    должен пройти через get_current_user так же, как обычный JWT.
    """

    @pytest.mark.asyncio
    async def test_create_and_use_token_via_real_endpoints(self, client, engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="pat_e2e_user", password="pass123")

        login_resp = await client.post("/auth/login", json={"username": "pat_e2e_user", "password": "pass123"})
        jwt_token = login_resp.json()["access_token"]

        create_resp = await client.post(
            "/api/tokens",
            json={"name": "CI script"},
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert create_resp.status_code == 201
        pat_token = create_resp.json()["token"]
        assert pat_token.startswith("pat_")

        # Используем PAT вместо JWT для следующего запроса
        list_resp = await client.get("/api/tokens", headers={"Authorization": f"Bearer {pat_token}"})
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1
        assert list_resp.json()[0]["name"] == "CI script"

    @pytest.mark.asyncio
    async def test_invalid_pat_returns_401(self, client):
        resp = await client.get("/api/tokens", headers={"Authorization": "Bearer pat_does-not-exist"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_revoked_token_returns_401_on_next_use(self, client, engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            await make_user(sess, username="pat_revoke_user", password="pass123")

        login_resp = await client.post("/auth/login", json={"username": "pat_revoke_user", "password": "pass123"})
        jwt_token = login_resp.json()["access_token"]

        create_resp = await client.post(
            "/api/tokens", json={"name": "X"}, headers={"Authorization": f"Bearer {jwt_token}"}
        )
        pat_token = create_resp.json()["token"]
        pat_id = create_resp.json()["id"]

        revoke_resp = await client.delete(f"/api/tokens/{pat_id}", headers={"Authorization": f"Bearer {jwt_token}"})
        assert revoke_resp.status_code == 200

        after_revoke = await client.get("/api/tokens", headers={"Authorization": f"Bearer {pat_token}"})
        assert after_revoke.status_code == 401
