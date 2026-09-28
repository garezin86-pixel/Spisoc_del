# tests/test_token_type.py
"""
Регрессионные тесты: аутентификацией служит ТОЛЬКО access-токен.

Промежуточный mfa_token (create_mfa_token) подписан тем же SECRET_KEY и
содержит "sub", поэтому раньше принимался get_current_user как обычный
access-токен — это позволяло обойти второй фактор 2FA, зная только пароль.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.config import ALGORITHM, SECRET_KEY
from src.core.dependencies import decode_access_token
from src.core.security import create_access_token, create_mfa_token, create_refresh_token
from tests.conftest import make_user

pytestmark = pytest.mark.asyncio

# Любой эндпоинт, требующий авторизации (Depends(get_current_user)).
PROTECTED_URL = "/api/auth/2fa/status"


async def _create_user(engine) -> int:
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as sess:
        user = await make_user(sess, username=f"tt_{uuid.uuid4().hex[:6]}")
        return user.id


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestGetCurrentUserRejectsNonAccessTokens:
    async def test_access_token_still_works(self, client, engine):
        user_id = await _create_user(engine)
        token = create_access_token({"sub": str(user_id)})

        resp = await client.get(PROTECTED_URL, headers=_bearer(token))

        assert resp.status_code == 200

    async def test_mfa_token_is_rejected(self, client, engine):
        """Главный кейс: mfa_token не должен заменять access-токен."""
        user_id = await _create_user(engine)
        token = create_mfa_token(user_id)

        resp = await client.get(PROTECTED_URL, headers=_bearer(token))

        assert resp.status_code == 401

    async def test_refresh_token_is_rejected(self, client, engine):
        user_id = await _create_user(engine)
        token, _jti = create_refresh_token(user_id)

        resp = await client.get(PROTECTED_URL, headers=_bearer(token))

        assert resp.status_code == 401

    async def test_token_without_type_is_rejected(self, client, engine):
        """JWT с верной подписью, но без claim type, не принимается."""
        user_id = await _create_user(engine)
        now = datetime.now(UTC)
        token = jwt.encode(
            {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=5)},
            SECRET_KEY,
            algorithm=ALGORITHM,
        )

        resp = await client.get(PROTECTED_URL, headers=_bearer(token))

        assert resp.status_code == 401


class TestDecodeAccessToken:
    """decode_access_token используется WebSocket-эндпоинтом (/api/ws)."""

    async def test_accepts_access_token(self):
        token = create_access_token({"sub": "1"})

        assert decode_access_token(token)["sub"] == "1"

    async def test_rejects_mfa_token(self):
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(create_mfa_token(1))

    async def test_rejects_token_without_type(self):
        now = datetime.now(UTC)
        token = jwt.encode(
            {"sub": "1", "iat": now, "exp": now + timedelta(minutes=5)},
            SECRET_KEY,
            algorithm=ALGORITHM,
        )

        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(token)
