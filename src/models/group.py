from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import Column, ForeignKey, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base

if TYPE_CHECKING:
    from src.models.task import SpisokModel
    from src.models.user import (
        UserModel,
    )


user_group = Table(
    "user_group",
    Base.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("group_id", ForeignKey("groups.id"), primary_key=True),
)


class GroupModel(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]

    users: Mapped[list["UserModel"]] = relationship(
        secondary=user_group,
        back_populates="groups",
        lazy="selectin",
        cascade="all, delete",
    )
    tasks: Mapped[list["SpisokModel"]] = relationship(
        "SpisokModel", back_populates="group", cascade="all, delete-orphan"
    )

    def __str__(self):
        return f"{self.name}"


class ConfirmDelete(BaseModel):
    group_name: str
