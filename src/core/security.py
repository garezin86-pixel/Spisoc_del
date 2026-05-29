from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta, UTC

from src.core.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, SECRET_KEY

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()

    now = datetime.now(UTC)
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": now})

    if not SECRET_KEY or not ALGORITHM:
        raise RuntimeError("JWT config missing")

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
