# src/models/task.py
from typing import Optional
from enum import Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, String, Index, DateTime
from datetime import datetime, timezone
import sqlalchemy as sa
from sqlalchemy import Enum as SAEnum
from src.db import Base
from src.models.audit import AuditMixin, SoftDeleteMixin
from typing import TYPE_CHECKING


class TaskPriority(str, Enum):
    """Приоритет задачи. Используется для сортировки и фильтрации."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


if TYPE_CHECKING:
    from src.models.user import (
        UserModel,
    )  # 👈 только для линтера, не создаёт циклического импорта
    from src.models.group import GroupModel


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SpisokModel(AuditMixin, SoftDeleteMixin, TimestampMixin, Base):
    __tablename__ = "spisok_del"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_done: Mapped[bool] = mapped_column(default=False)

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_sent: Mapped[bool] = mapped_column(
        default=False, server_default=sa.false(), nullable=False
    )
    priority: Mapped[TaskPriority] = mapped_column(
        SAEnum(TaskPriority, name="taskpriority"),
        default=TaskPriority.medium,
        server_default="medium",
        nullable=False,
    )

    user: Mapped["UserModel"] = relationship(
        "UserModel",
        foreign_keys=[user_id],
        back_populates="assigned_tasks",
        lazy="selectin",
    )
    author: Mapped["UserModel"] = relationship(
        "UserModel",
        foreign_keys=[author_id],
        back_populates="authored_tasks",
        lazy="selectin",
    )
    group: Mapped["GroupModel"] = relationship(
        "GroupModel", back_populates="tasks", lazy="selectin"
    )
    comments = relationship(
        "CommentModel",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    notification_logs = relationship(
        "NotificationLogModel", back_populates="task", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Простые индексы
        Index("ix_spisok_del_author_id", "author_id"),
        Index("ix_spisok_del_user_id", "user_id"),
        Index("ix_spisok_del_group_id", "group_id"),
        Index("ix_spisok_del_is_done", "is_done"),
        Index("ix_spisok_del_deadline", "deadline"),
        Index("ix_spisok_del_reminder_sent", "reminder_sent"),
        # Составные индексы
        Index("ix_spisok_del_author_done", "author_id", "is_done"),
        Index("ix_spisok_del_user_done", "user_id", "is_done"),
        Index("ix_spisok_del_group_done", "group_id", "is_done"),
        Index("ix_spisok_del_deadline_user", "deadline", "user_id"),
        Index("ix_spisok_del_done_deadline", "is_done", "deadline"),
        # Частичные индексы (PostgreSQL)
        Index(
            "ix_spisok_del_reminder_pending",
            "deadline",
            postgresql_where=sa.text(
                "reminder_sent = false AND is_done = false AND user_id IS NOT NULL"
            ),
        ),
        Index(
            "ix_spisok_del_not_deleted",
            "id",
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
        Index(
            "ix_spisok_del_user_not_deleted",
            "user_id",
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
        Index(
            "ix_spisok_del_group_not_deleted",
            "group_id",
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
    )

    def __str__(self):
        return f"{self.title}, id: {self.id}"
