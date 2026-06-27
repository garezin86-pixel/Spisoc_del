from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db import Base


class NotificationSettingsModel(Base):
    __tablename__ = "notification_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    # Типы уведомлений
    notify_deadline_24h: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_deadline_1h: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_overdue: Mapped[bool] = mapped_column(Boolean, default=True)
    weekly_report_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # опционально
    notify_task_assigned: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_task_updated: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_comment: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_group_assigned: Mapped[bool] = mapped_column(Boolean, default=True)  # Добавить

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationships
    user = relationship("UserModel", back_populates="notification_settings")

    __table_args__ = (
        # Простые индексы
        Index("ix_notification_settings_user_id", "user_id"),
        Index("ix_notification_settings_weekly_report_enabled", "weekly_report_enabled"),
        Index("ix_notification_settings_notify_deadline_24h", "notify_deadline_24h"),
        Index("ix_notification_settings_notify_deadline_1h", "notify_deadline_1h"),
        Index("ix_notification_settings_notify_overdue", "notify_overdue"),
        # Составные индексы
        Index("ix_notification_settings_user_weekly", "user_id", "weekly_report_enabled"),
        # Частичный индекс для пользователей с включённой еженедельной сводкой (PostgreSQL)
        Index(
            "ix_notification_settings_weekly_active",
            "user_id",
            postgresql_where=text("weekly_report_enabled = true"),
        ),
        # Частичный индекс для пользователей с любыми включёнными уведомлениями
        Index(
            "ix_notification_settings_any_enabled",
            "user_id",
            postgresql_where=text(
                "notify_deadline_24h = true "
                "OR notify_deadline_1h = true "
                "OR notify_overdue = true "
                "OR weekly_report_enabled = true"
            ),
        ),
    )
