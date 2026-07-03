# src/models/attachment.py
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base

if TYPE_CHECKING:
    from src.models.task import SpisokModel
    from src.models.user import UserModel


class AttachmentModel(Base):
    """
    Вложение к задаче.

    Фаза 1 (MVP): храним только telegram_file_id — Telegram сам держит файл.
    Фаза 2: добавим storage_url (S3/R2) для доступа с веба.
    """

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    task_id: Mapped[int] = mapped_column(
        ForeignKey("spisok_del.id", ondelete="CASCADE"),
        nullable=False,
    )
    uploaded_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Мета-данные файла
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(nullable=True)  # байты

    # Telegram file_id — заполняется только для файлов загруженных через бота.
    # Для веб-загрузок (POST /api/attachments/tasks/{id}) — None.
    telegram_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Фаза 2: зеркало в Cloudflare R2 для доступа с веба
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    task: Mapped["SpisokModel"] = relationship(
        "SpisokModel",
        back_populates="attachments",
    )
    uploader: Mapped["UserModel"] = relationship(
        "UserModel",
        back_populates="attachments",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_attachments_task_id", "task_id"),
        Index("ix_attachments_uploaded_by", "uploaded_by"),
    )

    def __repr__(self) -> str:
        return f"<Attachment id={self.id} task={self.task_id} file={self.filename!r}>"
