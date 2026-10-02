# src/models/mixins.py
"""Общие примеси (mixins) для моделей."""

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column


class TenantMixin:
    """Добавляет модели колонку workspace_id (NOT NULL, FK на workspaces).

    Значение подставляется автоматически слушателем SQLAlchemy "before_flush"
    из session.info["workspace_id"] — см. src/db/tenant_scope.py. Вызывающий
    код обычно НЕ должен передавать workspace_id в конструктор явно; если же
    передал — слушатель его не перезатирает.

    Порядок в списке базовых классов модели не важен, но традиционно ставьте
    TenantMixin последним перед Base, чтобы колонка была видна сразу под
    __tablename__ при чтении кода:
        class FooModel(SoftDeleteMixin, TenantMixin, Base):
    """

    workspace_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
