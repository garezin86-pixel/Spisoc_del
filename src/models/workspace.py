# src/models/workspace.py
"""Компания (арендатор) в мультитенантной версии Spisok Del.

Один workspace = одна компания. Пользователь принадлежит ровно одному
workspace (см. UserModel.workspace_id). Все данные компании (задачи, проекты,
теги и т.д.) помечены workspace_id через TenantMixin (см. src/models/mixins.py)
и не пересекаются между компаниями — см. фильтр в src/core/dependencies.py и
src/db/tenant_scope.py.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base

# id workspace, созданного миграцией a1b2c3d4e5f6 для существующих данных.
# Используется как явный fallback там, где workspace ещё не определён
# (например, старые фоновые задачи) — см. TODO в dependencies.py.
DEFAULT_WORKSPACE_SLUG = "default"


class WorkspaceModel(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Короткий машиночитаемый идентификатор компании: используется в ссылке-
    # приглашении бота (t.me/<bot>?start=ws_<slug>) и в будущем — в поддомене.
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __str__(self) -> str:
        return self.name
