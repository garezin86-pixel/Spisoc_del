# src/models/task.py
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base

# from enum import Enum
from src.models.audit import AuditMixin, SoftDeleteMixin
from src.models.enums import RecurrenceRule, TaskPriority, TaskStatus

if TYPE_CHECKING:
    from src.models.attachment_model import AttachmentModel
    from src.models.checklist import TaskChecklistItemModel
    from src.models.group import GroupModel
    from src.models.project import ProjectModel
    from src.models.tag import TagModel
    from src.models.user import (
        UserModel,
    )


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
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_sent: Mapped[bool] = mapped_column(default=False, server_default=sa.false(), nullable=False)
    priority: Mapped[TaskPriority] = mapped_column(
        SAEnum(TaskPriority, name="taskpriority"),
        default=TaskPriority.medium,
        server_default="medium",
        nullable=False,
    )

    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="taskstatus"),
        default=TaskStatus.todo,
        server_default="todo",
        nullable=False,
    )
    recurrence_rule: Mapped[RecurrenceRule] = mapped_column(
        SAEnum(RecurrenceRule, name="recurrencerule"),
        default=RecurrenceRule.none,
        server_default="none",
        nullable=False,
    )
    # Момент перехода в status=done — НЕ то же самое, что updated_at (тот
    # трогается при ЛЮБОМ изменении задачи, включая правки после завершения).
    # Нужен отдельно для точной аналитики "закрыто в срок/не в срок".
    # Обнуляется, если задачу переоткрыли (done -> любой другой статус).
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    group: Mapped["GroupModel"] = relationship("GroupModel", back_populates="tasks", lazy="selectin")
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
    notification_logs = relationship("NotificationLogModel", back_populates="task", cascade="all, delete-orphan")
    attachments: Mapped[list["AttachmentModel"]] = relationship(
        "AttachmentModel",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    checklist_items: Mapped[list["TaskChecklistItemModel"]] = relationship(
        "TaskChecklistItemModel",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskChecklistItemModel.order_index",
        lazy="selectin",
    )
    tags: Mapped[list["TagModel"]] = relationship(
        "TagModel",
        secondary="task_tags",
        back_populates="tasks",
        lazy="selectin",
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
            postgresql_where=sa.text("reminder_sent = false AND status != 'done' AND user_id IS NOT NULL"),
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
