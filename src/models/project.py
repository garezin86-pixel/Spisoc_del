# src/models/project.py
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db import Base

if TYPE_CHECKING:
    from src.models.user import UserModel
    from src.models.task import SpisokModel


# M2M таблица участников проекта
project_member = Table(
    "project_member",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "project_id", ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    ),
)


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

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

    # Владелец проекта
    owner: Mapped["UserModel"] = relationship(
        "UserModel",
        foreign_keys=[owner_id],
        back_populates="owned_projects",
        lazy="selectin",
    )

    # Участники (M2M)
    members: Mapped[list["UserModel"]] = relationship(
        secondary=project_member,
        back_populates="projects",
        lazy="selectin",
    )

    # Задачи проекта (при удалении проекта — задачи тоже удаляются)
    tasks: Mapped[list["SpisokModel"]] = relationship(
        "SpisokModel",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_projects_owner_id", "owner_id"),)

    def __str__(self):
        return f"{self.name} (id={self.id})"
