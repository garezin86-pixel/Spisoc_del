# src/models/task_dependency.py
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base

if TYPE_CHECKING:
    from src.models.task import SpisokModel


class TaskDependencyModel(Base):
    """
    Ребро графа "blocker блокирует blocked" (blocked не может перейти в done,
    пока blocker не закрыт). Простая M2M-таблица поверх spisok_del — без
    отдельного relationship-списка на SpisokModel (не хотим раздувать и без
    того большую модель задачи ещё двумя списками "blockers"/"blocked" ради
    фичи, которой не каждая команда будет пользоваться); чтение делается
    через TaskDependencyRepository напрямую.
    """

    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("blocker_task_id", "blocked_task_id", name="uq_task_dependency_pair"),
        CheckConstraint("blocker_task_id != blocked_task_id", name="ck_task_dependency_not_self"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # blocker должен быть закрыт (status=done) раньше, чем blocked сможет закрыться.
    blocker_task_id: Mapped[int] = mapped_column(ForeignKey("spisok_del.id", ondelete="CASCADE"), nullable=False)
    blocked_task_id: Mapped[int] = mapped_column(ForeignKey("spisok_del.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    blocker: Mapped["SpisokModel"] = relationship("SpisokModel", foreign_keys=[blocker_task_id])
    blocked: Mapped["SpisokModel"] = relationship("SpisokModel", foreign_keys=[blocked_task_id])

    def __str__(self) -> str:
        return f"#{self.blocker_task_id} блокирует #{self.blocked_task_id}"
