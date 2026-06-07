import jwt
import uuid
from passlib.context import CryptContext
from datetime import datetime, timedelta, UTC

from src.core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    SECRET_KEY,
    REFRESH_SECRET_KEY,
    REFRESH_TOKEN_EXPIRE_DAYS,
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
