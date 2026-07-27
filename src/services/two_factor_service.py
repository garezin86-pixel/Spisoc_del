# src/services/two_factor_service.py
import secrets

import pyotp

from src.core.constants import INVALID_CREDENTIALS
from src.core.exceptions import incorrect_request, invalid_credentials, unauthorized
from src.core.security import hash_password, verify_password
from src.models.user import UserModel
from src.repositories.two_factor_repository import TwoFactorRepository
from src.schemas.two_factor import (
    TwoFactorConfirmResponse,
    TwoFactorSetupResponse,
    TwoFactorStatusResponse,
)

ISSUER_NAME = "Spisok Del"
RECOVERY_CODES_COUNT = 10


def _generate_recovery_codes() -> list[str]:
    """10 одноразовых кодов вида xxxx-xxxx — компромисс между удобством ввода и энтропией."""
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(RECOVERY_CODES_COUNT)]


class TwoFactorService:
    def __init__(self, repo: TwoFactorRepository):
        self.repo = repo

    def status(self, user: UserModel) -> TwoFactorStatusResponse:
        return TwoFactorStatusResponse(
            enabled=user.totp_enabled,
            pending_setup=bool(user.totp_secret) and not user.totp_enabled,
        )

    async def start_setup(self, user: UserModel) -> TwoFactorSetupResponse:
        """
        Генерирует новый secret и сохраняет его как "ожидающий подтверждения"
        (totp_enabled остаётся False). Повторный вызов до confirm_setup
        перегенерирует secret — старый QR из предыдущей попытки станет
        нерабочим, это ожидаемо (защищает от гонки, если пользователь начал
        настройку дважды в разных вкладках).
        """
        secret = pyotp.random_base32()
        await self.repo.set_pending_secret(user, secret)
        otpauth_url = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=ISSUER_NAME)
        return TwoFactorSetupResponse(secret=secret, otpauth_url=otpauth_url)

    async def confirm_setup(self, user: UserModel, code: str) -> TwoFactorConfirmResponse:
        """Подтверждает setup первым верным кодом из аутентификатора — только
        после этого 2FA реально включается."""
        if not user.totp_secret:
            incorrect_request("Сначала запросите настройку 2FA (POST /auth/2fa/setup)")
        if not pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
            invalid_credentials("Неверный код. Проверьте время на телефоне и попробуйте снова")

        await self.repo.enable(user)
        recovery_codes = _generate_recovery_codes()
        await self.repo.replace_recovery_codes(user.id, [hash_password(c) for c in recovery_codes])
        return TwoFactorConfirmResponse(recovery_codes=recovery_codes)

    async def disable(self, user: UserModel, password: str, code: str) -> None:
        """Требует и пароль, и второй фактор — угнанный access-токен сам по себе не должен позволять снять 2FA."""
        if not verify_password(password, user.password_hash):
            invalid_credentials(INVALID_CREDENTIALS)
        if not await self._verify_code_or_recovery(user, code):
            invalid_credentials("Неверный код 2FA")
        await self.repo.disable(user)

    async def verify_login_code(self, user: UserModel, code: str) -> None:
        """Проверка второго фактора на шаге логина — бросает 401 при неверном коде, ничего не возвращает при успехе."""
        if not await self._verify_code_or_recovery(user, code):
            unauthorized("Неверный код 2FA")

    async def _verify_code_or_recovery(self, user: UserModel, code: str) -> bool:
        if not user.totp_secret:
            return False
        if pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
            return True
        return await self._try_consume_recovery_code(user, code)

    async def _try_consume_recovery_code(self, user: UserModel, code: str) -> bool:
        candidates = await self.repo.get_unused_recovery_codes(user.id)
        for candidate in candidates:
            if verify_password(code, candidate.code_hash):
                await self.repo.mark_recovery_code_used(candidate)
                return True
        return False
