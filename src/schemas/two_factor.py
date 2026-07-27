# src/schemas/two_factor.py
from pydantic import BaseModel, Field


class TwoFactorStatusResponse(BaseModel):
    enabled: bool
    pending_setup: bool  # secret сгенерирован, но ещё не подтверждён кодом


class TwoFactorSetupResponse(BaseModel):
    secret: str
    otpauth_url: str = Field(description="Ссылка вида otpauth://totp/... — из неё фронтенд рисует QR-код")


class TwoFactorConfirmRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TwoFactorConfirmResponse(BaseModel):
    recovery_codes: list[str] = Field(
        description=(
            "Показываются ОДИН раз. Каждый код одноразовый — используется, если устройство с аутентификатором утеряно."
        )
    )


class TwoFactorDisableRequest(BaseModel):
    password: str = Field(
        ..., description="Требуем пароль ещё раз — иначе угнанный access-токен позволил бы тихо снять 2FA"
    )
    code: str = Field(..., description="TOTP-код или один из recovery-кодов")
