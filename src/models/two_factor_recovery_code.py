# src/models/two_factor_recovery_code.py
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base

if TYPE_CHECKING:
    from src.models.user import UserModel


class TwoFactorRecoveryCodeModel(Base):
    """
    Одноразовые резервные коды для входа при утере устройства с
    аутентификатором. Хранятся хэшем (bcrypt через тот же pwd_context, что
    и пароли) — в отличие от totp_secret и webhook.secret, здесь сервер
    только СВЕРЯЕТ введённый код с хэшем, а не вычисляет его сам, поэтому
    хэширование уместно и безопаснее, чем открытое хранение.
    """

    __tablename__ = "two_factor_recovery_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["UserModel"] = relationship("UserModel", back_populates="two_factor_recovery_codes")
