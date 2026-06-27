from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base
from src.models.group import user_group

if TYPE_CHECKING:
    from src.models.comment import CommentModel
    from src.models.group import GroupModel
    from src.models.project import ProjectModel


class UserRole(str, Enum):
    admin = "admin"
    manager = "manager"
    user = "user"

    def __str__(self) -> str:
        return self.value


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    role: Mapped[str] = mapped_column(String, default=UserRole.user)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)

    assigned_tasks = relationship("SpisokModel", foreign_keys="[SpisokModel.user_id]", back_populates="user")
    authored_tasks = relationship(
        "SpisokModel",
        foreign_keys="[SpisokModel.author_id]",
        back_populates="author",
        cascade="all, delete",
    )
    groups: Mapped[list["GroupModel"]] = relationship(secondary=user_group, back_populates="users", lazy="selectin")
    comments: Mapped[list["CommentModel"]] = relationship(back_populates="user")

    # Relationships
    notification_settings = relationship("NotificationSettingsModel", back_populates="user", uselist=False)

    notification_logs = relationship("NotificationLogModel", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_users_telegram_active", "telegram_id", "is_active"),)

    owned_projects: Mapped[list["ProjectModel"]] = relationship(
        "ProjectModel",
        foreign_keys="[ProjectModel.owner_id]",
        back_populates="owner",
        lazy="selectin",
    )
    projects: Mapped[list["ProjectModel"]] = relationship(
        "ProjectModel",
        secondary="project_member",
        back_populates="members",
        lazy="selectin",
    )

    def __str__(self):
        return f"{self.username}"
