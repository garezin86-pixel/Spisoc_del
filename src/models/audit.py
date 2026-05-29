# src/models/audit.py
"""
AuditLog модель + миксины SoftDeleteMixin и AuditMixin.

Адаптировано под проект:
  - Base из src.db
  - AsyncSession (asyncpg) — event listener остаётся синхронным,
    это нормально: SQLAlchemy events всегда sync даже при async engine
  - UnitOfWork паттерн — user_id передаётся через session.info
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    event,
    inspect as sa_inspect,
    text,
)

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
import sqlalchemy as sa

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship
from src.db import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.user import (
        UserModel,
    )  # 👈 только для линтера, не создаёт циклического импорта


# Универсальный тип: JSONB на PostgreSQL, JSON на SQLite
SmartJSON = sa.type_coerce  # не нужно, просто меняем колонки:


# ─────────────────────────────────────────────────────────────────────────────
# Enum действий
# ─────────────────────────────────────────────────────────────────────────────
class AuditAction(str, enum.Enum):
    create = "create"
    update = "update"
    delete = "delete"
    restore = "restore"


# ─────────────────────────────────────────────────────────────────────────────
# Модель AuditLog
# ─────────────────────────────────────────────────────────────────────────────
class AuditLog(Base):
    """
    История изменений любых сущностей проекта.

    Пример записи:
        entity_type = "spisok_del"
        entity_id   = 42
        action      = AuditAction.update
        old_values  = {"is_done": false}
        new_values  = {"is_done": true}
        user_id     = 7
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    # NULL — для фоновых задач (Telegram-бот, планировщик)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Имя таблицы: "spisok_del", "comments", "users", ...
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)

    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, name="audit_action_enum"), nullable=False
    )

    # Только изменившиеся поля (не весь объект)
    # old_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # new_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Стало

    old_values: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    new_values: Mapped[dict | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )

    # changed_at: Mapped[datetime] = mapped_column(
    #     DateTime(timezone=True),
    #     nullable=False,
    #     server_default=text("now()"),
    # )
    # Стало
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("(CURRENT_TIMESTAMP)"),
    )

    # Relationship к пользователю (для отображения имени в истории)
    user: Mapped["UserModel"] = relationship(
        "UserModel",
        foreign_keys=[user_id],
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog {self.entity_type}#{self.entity_id} "
            f"action={self.action} user={self.user_id}>"
        )


# ─────────────────────────────────────────────────────────────────────────────
# SoftDeleteMixin
# ─────────────────────────────────────────────────────────────────────────────
class SoftDeleteMixin:
    """
    Мягкое удаление через поле deleted_at.

    ── Использование в TaskService ──────────────────────────────────────────
        # Передаём user_id один раз на запрос
        session.info["audit_user_id"] = current_user.id

        task.soft_delete(session)       # помечает удалённым + пишет в audit_log
        await session.commit()

        task.restore(session)           # восстанавливает
        await session.commit()

    ── Фильтрация в репозитории ─────────────────────────────────────────────
        # Только живые задачи:
        select(SpisokModel).where(SpisokModel.not_deleted_filter())

        # Только удалённые (например, для корзины):
        select(SpisokModel).where(SpisokModel.deleted_at.isnot(None))
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, session: AsyncSession | Session) -> None:
        """Помечает запись удалённой. user_id берётся из session.info."""
        if self.is_deleted:
            return

        user_id: int | None = session.info.get("audit_user_id")
        now = datetime.now(timezone.utc)
        self.deleted_at = now  # 👈 теперь тип точно datetime, не datetime | None

        session.add(
            AuditLog(
                user_id=user_id,
                entity_type=self.__tablename__,  # type: ignore[attr-defined]
                entity_id=self.id,  # type: ignore[attr-defined]
                action=AuditAction.delete,
                old_values={"deleted_at": None},
                new_values={"deleted_at": now.isoformat()},
            )
        )

    def restore(self, session: AsyncSession | Session) -> None:
        """Восстанавливает мягко удалённую запись."""
        if not self.is_deleted:
            return

        user_id: int | None = session.info.get("audit_user_id")
        old_ts = self.deleted_at.isoformat() if self.deleted_at else None
        self.deleted_at = None

        session.add(
            AuditLog(
                user_id=user_id,
                entity_type=self.__tablename__,  # type: ignore[attr-defined]
                entity_id=self.id,  # type: ignore[attr-defined]
                action=AuditAction.restore,
                old_values={"deleted_at": old_ts},
                new_values={"deleted_at": None},
            )
        )

    @classmethod
    def not_deleted_filter(cls):
        """Готовый фильтр для запросов — только не удалённые записи."""
        return cls.deleted_at.is_(None)


# ─────────────────────────────────────────────────────────────────────────────
# AuditMixin — автоматический аудит CREATE / UPDATE
# ─────────────────────────────────────────────────────────────────────────────

# Поля, изменения которых не нужно логировать
_SKIP_FIELDS = frozenset(
    {
        "updated_at",
        "deleted_at",  # логируется отдельно через soft_delete() / restore()
        "reminder_sent",  # технический флаг планировщика
    }
)


class AuditMixin:
    """
    Добавьте к модели — CREATE и UPDATE будут автоматически
    попадать в audit_log через SQLAlchemy after_flush event.

    Передача user_id (один раз в начале обработки запроса):
        session.info["audit_user_id"] = current_user.id

    Уже применён к: SpisokModel, CommentModel
    Можно добавить к: UserModel, GroupModel и др.
    """


# ── Вспомогательные функции ──────────────────────────────────────────────────


def _serialize(value: Any) -> Any:
    """Приводит значение к JSON-сериализуемому виду."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _changed_fields(instance: Any) -> tuple[dict, dict]:
    """Возвращает (old_values, new_values) только для реально изменившихся полей."""
    old: dict = {}
    new: dict = {}

    try:
        attrs = sa_inspect(instance).attrs
    except Exception:
        return old, new

    for attr in attrs:
        key = attr.key
        if key in _SKIP_FIELDS:
            continue
        hist = attr.history
        if not hist.has_changes():
            continue
        old_val = hist.deleted[0] if hist.deleted else None
        new_val = hist.added[0] if hist.added else None
        if old_val != new_val:
            old[key] = _serialize(old_val)
            new[key] = _serialize(new_val)

    return old, new


# ── Event listener ────────────────────────────────────────────────────────────
@event.listens_for(Session, "after_flush")
def _on_after_flush(session: Session | AsyncSession, flush_context: Any) -> None:
    """
    Перехватывает INSERT и UPDATE для всех моделей с AuditMixin.
    AuditLog сам AuditMixin не наследует — рекурсии нет.
    """
    user_id: int | None = session.info.get("audit_user_id")
    entries: list[AuditLog] = []

    for instance in list(session.new):
        if not isinstance(instance, AuditMixin):
            continue
        _, new_vals = _changed_fields(instance)
        entries.append(
            AuditLog(
                user_id=user_id,
                entity_type=instance.__tablename__,  # type: ignore[attr-defined]
                entity_id=instance.id,  # type: ignore[attr-defined]
                action=AuditAction.create,
                old_values=None,
                new_values=new_vals or None,
            )
        )

    for instance in list(session.dirty):
        if not isinstance(instance, AuditMixin):
            continue
        old_vals, new_vals = _changed_fields(instance)
        if not old_vals:
            continue  # ничего значимого не изменилось
        entries.append(
            AuditLog(
                user_id=user_id,
                entity_type=instance.__tablename__,  # type: ignore[attr-defined]
                entity_id=instance.id,  # type: ignore[attr-defined]
                action=AuditAction.update,
                old_values=old_vals,
                new_values=new_vals,
            )
        )

    for entry in entries:
        session.add(entry)
