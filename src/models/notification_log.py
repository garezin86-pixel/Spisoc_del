from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Boolean, String, ForeignKey, DateTime
from datetime import datetime, timezone
from src.db import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.user import UserModel
    from src.models.task import SpisokModel


class NotificationLogModel(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    notification_type: Mapped[str] = mapped_column(
        String(50)
    )  # deadline_24h, overdue, etc.
    task_id: Mapped[int] = mapped_column(
        ForeignKey("spisok_del.id", ondelete="SET NULL"), nullable=True
    )
    content: Mapped[str] = mapped_column(String(2000))
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(String(500), nullable=True)

    # ✅ Добавляем relationship для доступа к пользователю
    user: Mapped["UserModel"] = relationship(back_populates="notification_logs")

    # Опционально: relationship для задачи
    task: Mapped["SpisokModel"] = relationship(
        back_populates="notification_logs", foreign_keys=[task_id]
    )
