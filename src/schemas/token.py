from pydantic import BaseModel


class TokenSchema(BaseModel):
    """
    Обычный логин (без 2FA или уже пройденного 2FA): access_token/refresh_token
    заполнены, mfa_required=False.

    Логин пользователя с включённой 2FA, до ввода кода: access_token и
    refresh_token — None, mfa_required=True, mfa_token заполнен — им нужно
    сходить в POST /auth/login/2fa вместе с TOTP-кодом, чтобы получить
    настоящие токены.
    """

    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_token: str | None = None
    # Мягкое напоминание для admin/manager без включённой 2FA — вход всё
    # равно проходит успешно (см. two_factor_service.py: намеренно не
    # блокируем логин админам без 2FA, чтобы не запереть единственную
    # админ-учётку после деплоя), но фронтенд может показать баннер.
    requires_2fa_setup: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class TwoFactorLoginRequest(BaseModel):
    mfa_token: str
    code: str
