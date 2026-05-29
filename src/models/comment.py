# src/models/comment.py
from sqlalchemy import ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from sqlalchemy import func
from src.db import Base

from src.models.audit import AuditMixin, SoftDeleteMixin
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.user import (
        UserModel,
    )  # 👈 только для линтера, не создаёт циклического импорта


class CommentModel(AuditMixin, SoftDeleteMixin, Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("spisok_del.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    task = relationship("SpisokModel", back_populates="comments")
    user: Mapped["UserModel"] = relationship(back_populates="comments")

    def __str__(self):
        return f"{self.content}"
