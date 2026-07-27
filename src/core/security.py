import uuid
from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext

from src.core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    REFRESH_SECRET_KEY,
    REFRESH_TOKEN_EXPIRE_DAYS,
    SECRET_KEY,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def create_access_token(data: dict) -> str:
    """Короткоживущий токен (15-30 мин). Содержит sub, role, username."""
    to_encode = data.copy()
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": now, "type": "access"})

    if not SECRET_KEY or not ALGORITHM:
        raise RuntimeError("JWT config missing")

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: int) -> tuple[str, str]:
    """Долгоживущий токен (30 дней). Подписан отдельным ключом.

    Возвращает (token, jti) — jti нужен для хранения в Redis.
    jti (JWT ID) — уникальный идентификатор этого конкретного токена.
    Именно его мы кладём в Redis, чтобы можно было отозвать.
    """
    jti = str(uuid.uuid4())
    now = datetime.now(UTC)
    expire = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    payload = {
        "sub": str(user_id),
        "jti": jti,
        "exp": expire,
        "iat": now,
        "type": "refresh",
    }

    token = jwt.encode(payload, REFRESH_SECRET_KEY, algorithm=ALGORITHM)
    return token, jti


def decode_refresh_token(token: str) -> dict:
    """Декодирует refresh token. Бросает jwt.PyJWTError при невалидном токене."""
    return jwt.decode(token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])


# Окно, в течение которого нужно ввести код 2FA после успешной проверки
# пароля. Короткое намеренно — это не сессионный токен, а промежуточное
# состояние "пароль верный, ждём второй фактор".
MFA_TOKEN_EXPIRE_MINUTES = 5


def create_mfa_token(user_id: int) -> str:
    """
    Промежуточный токен между вводом пароля и вводом TOTP-кода. Подписан
    тем же SECRET_KEY, что и access token, но с "type": "mfa" — так что
    даже если он утечёт, им нельзя авторизоваться как обычным access-токеном
    (get_current_user проверяет type; см. decode_mfa_token — обратное тоже
    верно, access token не пройдёт как mfa_token).
    """
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": "mfa",
        "iat": now,
        "exp": now + timedelta(minutes=MFA_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_mfa_token(token: str) -> dict:
    """Декодирует mfa_token. Бросает jwt.PyJWTError при невалидном/истёкшем токене."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("type") != "mfa":
        raise jwt.InvalidTokenError("Not an MFA token")
    return payload
