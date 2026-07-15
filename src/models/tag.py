# src/models/tag.py
from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base

if TYPE_CHECKING:
    from src.models.task import SpisokModel

# Многие-ко-многим: одна задача — несколько тегов, один тег — много задач.
task_tags = Table(
    "task_tags",
    Base.metadata,
    Column("task_id", ForeignKey("spisok_del.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class TagModel(Base):
    """Свободный тег для задач (например, #клиент-X, #срочно-не-по-дедлайну).

    Теги глобальны для всей команды (не привязаны к одному пользователю) —
    это упрощённая модель, подходящая для небольшой команды, где теги — это
    общий словарь меток, а не личное пространство каждого. Имя уникально
    без учёта регистра, чтобы "Клиент" и "клиент" не плодили дубликаты.
    """

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#6b7280", server_default="#6b7280")

    tasks: Mapped[list["SpisokModel"]] = relationship(
        "SpisokModel",
        secondary=task_tags,
        back_populates="tags",
        lazy="selectin",
    )

    def __str__(self) -> str:
        return self.name
