# tests/test_two_factor.py
import uuid

import pyotp
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.repositories.two_factor_repository import TwoFactorRepository
from src.services.two_factor_service import TwoFactorService
from tests.conftest import make_user

pytestmark = pytest.mark.asyncio


def build_service(session) -> TwoFactorService:
    return TwoFactorService(TwoFactorRepository(session))


async def _enable_2fa(session, user) -> str:
    """Хелпер: проходит setup+confirm и возвращает secret (для генерации валидных кодов в тестах)."""
    service = build_service(session)
    setup = await service.start_setup(user)
    code = pyotp.TOTP(setup.secret).now()
    await service.confirm_setup(user, code)
    return setup.secret


class TestTwoFactorServiceSetup:
    async def test_status_initially_disabled(self, session):
        user = await make_user(session)
        service = build_service(session)

        status = service.status(user)

        assert status.enabled is False
        assert status.pending_setup is False

    async def test_start_setup_generates_secret_and_url(self, session):
        user = await make_user(session)
        service = build_service(session)

        result = await service.start_setup(user)

        assert len(result.secret) >= 16
        assert result.otpauth_url.startswith("otpauth://totp/")
        assert "Spisok" in result.otpauth_url
        assert result.secret in result.otpauth_url

    async def test_start_setup_does_not_enable_yet(self, session):
        user = await make_user(session)
        service = build_service(session)

        await service.start_setup(user)

        status = service.status(user)
        assert status.enabled is False
        assert status.pending_setup is True

    async def test_confirm_setup_with_valid_code_enables_2fa(self, session):
        user = await make_user(session)
        service = build_service(session)
        setup = await service.start_setup(user)
        code = pyotp.TOTP(setup.secret).now()

        await service.confirm_setup(user, code)

        assert user.totp_enabled is True

    async def test_confirm_setup_returns_ten_recovery_codes(self, session):
        user = await make_user(session)
        service = build_service(session)
        setup = await service.start_setup(user)
        code = pyotp.TOTP(setup.secret).now()

        result = await service.confirm_setup(user, code)

        assert len(result.recovery_codes) == 10
        assert len(set(result.recovery_codes)) == 10  # все разные

    async def test_confirm_setup_with_invalid_code_rejected(self, session):
        user = await make_user(session)
        service = build_service(session)
        await service.start_setup(user)

        with pytest.raises(Exception) as exc_info:
            await service.confirm_setup(user, "000000")
        assert getattr(exc_info.value, "status_code", None) == 401
        assert user.totp_enabled is False

    async def test_confirm_setup_without_pending_secret_rejected(self, session):
        user = await make_user(session)
        service = build_service(session)

        with pytest.raises(Exception) as exc_info:
            await service.confirm_setup(user, "123456")
        assert getattr(exc_info.value, "status_code", None) == 400


class TestTwoFactorServiceVerifyAndDisable:
    async def test_verify_login_code_accepts_valid_totp(self, session):
        user = await make_user(session)
        secret = await _enable_2fa(session, user)
        service = build_service(session)

        await service.verify_login_code(user, pyotp.TOTP(secret).now())  # не должно упасть

    async def test_verify_login_code_rejects_invalid(self, session):
        user = await make_user(session)
        await _enable_2fa(session, user)
        service = build_service(session)

        with pytest.raises(Exception) as exc_info:
            await service.verify_login_code(user, "000000")
        assert getattr(exc_info.value, "status_code", None) == 401

    async def test_recovery_code_accepted_and_single_use(self, session):
        user = await make_user(session)
        service = build_service(session)
        setup = await service.start_setup(user)
        confirm = await service.confirm_setup(user, pyotp.TOTP(setup.secret).now())
        recovery_code = confirm.recovery_codes[0]

        await service.verify_login_code(user, recovery_code)  # первое использование — ок

        with pytest.raises(Exception) as exc_info:
            await service.verify_login_code(user, recovery_code)  # повторное — уже нет
        assert getattr(exc_info.value, "status_code", None) == 401

    async def test_disable_requires_correct_password(self, session):
        user = await make_user(session, password="correct-pass")
        secret = await _enable_2fa(session, user)
        service = build_service(session)

        with pytest.raises(Exception) as exc_info:
            await service.disable(user, "wrong-pass", pyotp.TOTP(secret).now())
        assert getattr(exc_info.value, "status_code", None) == 401

    async def test_disable_requires_correct_code(self, session):
        user = await make_user(session, password="correct-pass")
        await _enable_2fa(session, user)
        service = build_service(session)

        with pytest.raises(Exception) as exc_info:
            await service.disable(user, "correct-pass", "000000")
        assert getattr(exc_info.value, "status_code", None) == 401

    async def test_disable_clears_secret_and_enabled_flag(self, session):
        user = await make_user(session, password="correct-pass")
        secret = await _enable_2fa(session, user)
        service = build_service(session)

        await service.disable(user, "correct-pass", pyotp.TOTP(secret).now())

        assert user.totp_enabled is False
        assert user.totp_secret is None


class TestTwoFactorLoginFlowViaRealApp:
    async def _create_user(self, engine, username: str, password: str = "pass123", role: str = "user"):
        async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with async_session() as sess:
            user = await make_user(sess, username=username, password=password, role=role)
            return user.id

    async def test_login_without_2fa_returns_tokens_directly(self, client, engine):
        username = f"u2fa_{uuid.uuid4().hex[:6]}"
        await self._create_user(engine, username)

        resp = await client.post("/auth/login", json={"username": username, "password": "pass123"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] is not None
        assert data["mfa_required"] is False

    async def test_admin_without_2fa_gets_nudge_flag(self, client, engine):
        username = f"admin_{uuid.uuid4().hex[:6]}"
        await self._create_user(engine, username, role="admin")

        resp = await client.post("/auth/login", json={"username": username, "password": "pass123"})

        assert resp.status_code == 200
        assert resp.json()["requires_2fa_setup"] is True

    async def test_regular_user_without_2fa_no_nudge_flag(self, client, engine):
        username = f"user_{uuid.uuid4().hex[:6]}"
        await self._create_user(engine, username, role="user")

        resp = await client.post("/auth/login", json={"username": username, "password": "pass123"})

        assert resp.json()["requires_2fa_setup"] is False

    async def test_full_setup_and_login_flow_via_http(self, client, engine):
        username = f"full_{uuid.uuid4().hex[:6]}"
        await self._create_user(engine, username)
        login_resp = await client.post("/auth/login", json={"username": username, "password": "pass123"})
        jwt_token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {jwt_token}"}

        setup_resp = await client.post("/api/auth/2fa/setup", headers=headers)
        assert setup_resp.status_code == 200
        secret = setup_resp.json()["secret"]

        confirm_resp = await client.post(
            "/api/auth/2fa/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=headers
        )
        assert confirm_resp.status_code == 200
        assert len(confirm_resp.json()["recovery_codes"]) == 10

        status_resp = await client.get("/api/auth/2fa/status", headers=headers)
        assert status_resp.json()["enabled"] is True

        # Логин теперь должен требовать второй фактор
        second_login = await client.post("/auth/login", json={"username": username, "password": "pass123"})
        assert second_login.json()["mfa_required"] is True
        mfa_token = second_login.json()["mfa_token"]

        final = await client.post("/auth/login/2fa", json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()})
        assert final.status_code == 200
        assert final.json()["access_token"] is not None

    async def test_login_2fa_rejects_wrong_code(self, client, engine):
        username = f"wrongcode_{uuid.uuid4().hex[:6]}"
        await self._create_user(engine, username)
        login_resp = await client.post("/auth/login", json={"username": username, "password": "pass123"})
        headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}
        setup_resp = await client.post("/api/auth/2fa/setup", headers=headers)
        secret = setup_resp.json()["secret"]
        await client.post("/api/auth/2fa/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=headers)

        second_login = await client.post("/auth/login", json={"username": username, "password": "pass123"})
        mfa_token = second_login.json()["mfa_token"]

        resp = await client.post("/auth/login/2fa", json={"mfa_token": mfa_token, "code": "000000"})

        assert resp.status_code == 401

    async def test_login_2fa_rejects_garbage_mfa_token(self, client):
        resp = await client.post("/auth/login/2fa", json={"mfa_token": "not-a-real-token", "code": "123456"})
        assert resp.status_code == 401

    async def test_disable_via_http(self, client, engine):
        username = f"disable_{uuid.uuid4().hex[:6]}"
        await self._create_user(engine, username)
        login_resp = await client.post("/auth/login", json={"username": username, "password": "pass123"})
        headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}
        setup_resp = await client.post("/api/auth/2fa/setup", headers=headers)
        secret = setup_resp.json()["secret"]
        await client.post("/api/auth/2fa/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=headers)

        disable_resp = await client.post(
            "/api/auth/2fa/disable",
            json={"password": "pass123", "code": pyotp.TOTP(secret).now()},
            headers=headers,
        )
        assert disable_resp.status_code == 204

        # После отключения — обычный логин без запроса второго фактора
        after = await client.post("/auth/login", json={"username": username, "password": "pass123"})
        assert after.json()["mfa_required"] is False
