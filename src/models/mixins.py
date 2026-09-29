# src/models/mixins.py
"""Общие примеси (mixins) для моделей."""

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column


class TenantMixin:
    """Добавляет модели колонку workspace_id.

    Nullable на переходный период (Этап 0.5, шаг 1 миграции): существующие
    строки получат id Default workspace отдельной data-миграцией (шаг 2),
    после чего колонка станет NOT NULL (шаг 3). Не добавляйте новых записей
    без workspace_id — фильтр в src/db/tenant_scope.py считает NULL "ничьим"
    и в чтение по конкретному workspace такие строки не попадут.

    Порядок в списке базовых классов модели не важен, но традиционно ставьте
    TenantMixin последним перед Base, чтобы колонка была видна сразу под
    __tablename__ при чтении кода:
        class FooModel(SoftDeleteMixin, TenantMixin, Base):
    """

    workspace_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
