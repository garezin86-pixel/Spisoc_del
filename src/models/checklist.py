# src/models/checklist.py
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base

if TYPE_CHECKING:
    from src.models.task import SpisokModel


class TaskChecklistItemModel(Base):
    """Пункт чек-листа внутри задачи (подзадача без собственного жизненного цикла).

    В отличие от полноценной задачи (SpisokModel), пункт чек-листа не имеет
    своего исполнителя, дедлайна или статуса в канбане — только галочку
    "сделано/не сделано" и порядок отображения. Подходит для декомпозиции
    задачи вроде "подготовить отчёт" на конкретные шаги.
    """

    __tablename__ = "task_checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("spisok_del.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    task: Mapped["SpisokModel"] = relationship("SpisokModel", back_populates="checklist_items")

    def __str__(self) -> str:
        return f"[{'x' if self.is_done else ' '}] {self.title}"
