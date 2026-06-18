# src/models/task.py
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, String, Index, DateTime
from datetime import datetime, timezone
import sqlalchemy as sa
from src.db import Base
from sqlalchemy import Enum as SAEnum
from enum import Enum
from src.models.audit import AuditMixin, SoftDeleteMixin
from typing import TYPE_CHECKING


class TaskPriority(str, Enum):
    """Приоритет задачи. Используется для сортировки и фильтрации."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TaskStatus(str, Enum):
    """Статус задачи для канбан-доски."""

    backlog = "backlog"  # Очередь
    todo = "todo"  # Новые
    in_progress = "in_progress"  # В работе
    review = "review"  # На проверке
    done = "done"  # Готово


if TYPE_CHECKING:
    from src.models.user import (
        UserModel,
    )  # 👈 только для линтера, не создаёт циклического импорта
    from src.models.group import GroupModel
    from src.models.project import ProjectModel


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

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="taskstatus"),
        default=TaskStatus.todo,
        server_default="todo",
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
    project: Mapped[Optional["ProjectModel"]] = relationship(
        "ProjectModel",
        back_populates="tasks",
        lazy="selectin",
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
        Index("ix_spisok_del_status", "status"),
        Index("ix_spisok_del_deadline", "deadline"),
        Index("ix_spisok_del_reminder_sent", "reminder_sent"),
        # Составные индексы
        Index("ix_spisok_del_author_done", "author_id", "status"),
        Index("ix_spisok_del_user_done", "user_id", "status"),
        Index("ix_spisok_del_group_done", "group_id", "status"),
        Index("ix_spisok_del_deadline_user", "deadline", "user_id"),
        Index("ix_spisok_del_done_deadline", "status", "deadline"),
        # Частичные индексы (PostgreSQL)
        Index(
            "ix_spisok_del_reminder_pending",
            "deadline",
            postgresql_where=sa.text(
                "reminder_sent = false AND status != 'done' AND user_id IS NOT NULL"
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
