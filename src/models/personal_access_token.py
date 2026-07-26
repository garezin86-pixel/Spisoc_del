# src/models/personal_access_token.py
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base
from src.models.enums import PatScope

if TYPE_CHECKING:
    from src.models.user import UserModel


class PersonalAccessTokenModel(Base):
    """
    Персональный API-токен — альтернатива JWT-сессии для скриптов и
    интеграций (Zapier-подобные сценарии, личные автоматизации), которым
    неудобно перелогиниваться каждые ACCESS_TOKEN_EXPIRE_MINUTES (30 мин).

    Хранится только SHA-256 хэш токена, не сам токен — как и с паролями,
    сырое значение известно пользователю лишь один раз, в момент создания.
    В отличие от паролей здесь НЕ используется bcrypt: bcrypt рассчитан на
    защиту низкоэнтропийных человеческих паролей от подбора, а токен —
    это 32 случайных байта (token_urlsafe), уже неподбираемые напрямую;
    быстрый SHA-256 достаточен и не создаёт лишней CPU-нагрузки на каждый
    API-запрос (в отличие от логина, аутентификация по PAT происходит на
    КАЖДЫЙ вызов API, а не один раз за сессию).
    """

    __tablename__ = "personal_access_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Первые символы токена — для отображения в списке ("pat_a1b2c3d4..."),
    # чтобы пользователь мог опознать токен, не имея возможности его скачать заново.
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    # read_only | read_write. String, а не нативный Postgres ENUM — так же,
    # как UserModel.role, ради простоты миграций (добавить значение в Python
    # enum не требует ALTER TYPE).
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default=PatScope.read_write)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["UserModel"] = relationship("UserModel", back_populates="personal_access_tokens")

    def __str__(self) -> str:
        return f"{self.name} ({self.token_prefix}…)"
