from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, String, Text, DateTime, Integer
from sqlalchemy import Enum as SAEnum
from datetime import datetime, timezone
from src.db import Base
from src.models.task import TaskPriority


class TaskTemplateModel(Base):
    __tablename__ = "task_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = relationship("UserModel", lazy="joined")
    items = relationship(
        "TaskTemplateItemModel",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="TaskTemplateItemModel.order_index",
        lazy="joined",
    )

    def __str__(self):
        return self.title

    def __repr__(self):
        return f"<TaskTemplateModel id={self.id} title='{self.title}'>"


class TaskTemplateItemModel(Base):
    __tablename__ = "task_template_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("task_templates.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[TaskPriority] = mapped_column(
        SAEnum(TaskPriority, name="taskpriority", create_type=False),
        nullable=False,
        default=TaskPriority.medium,
        server_default="medium",
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    template = relationship("TaskTemplateModel", back_populates="items")
