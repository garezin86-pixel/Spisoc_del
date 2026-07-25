# src/models/filter_preset.py
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.models.enums import TaskPriority, TaskStatus


class FilterPresetModel(Base):
    """Именованный набор фильтров списка задач (/tasks/filter), сохранённый
    пользователем — чтобы не собирать комбинацию status+priority+tag_id заново
    каждый раз (например, "Мои горящие" = in_progress + high + тег).

    filter_user_group хранится как обычная строка (а не SAEnum), т.к.
    FilterUserGroup сейчас определён в src/schemas/task.py — модели слоя БД
    не должны зависеть от схем API. Валидация значения происходит на уровне
    Pydantic-схемы (FilterPresetCreate), а не здесь.
    """

    __tablename__ = "filter_presets"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_filter_preset_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    status: Mapped[TaskStatus | None] = mapped_column(SAEnum(TaskStatus, name="taskstatus"), nullable=True)
    priority: Mapped[TaskPriority | None] = mapped_column(SAEnum(TaskPriority, name="taskpriority"), nullable=True)
    tag_id: Mapped[int | None] = mapped_column(ForeignKey("tags.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    filter_user_group: Mapped[str | None] = mapped_column(String(20), nullable=True)
    filter_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __str__(self):
        return f"{self.name} (user_id={self.user_id})"
