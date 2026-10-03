# src/models/workspace_invite.py
"""Приглашение в workspace (компанию).

Админ компании создаёт приглашение и отдаёт сотруднику ссылку: в веб —
регистрация с invite_token, в Telegram-боте — t.me/<бот>?start=ws_<token>.
Присоединившийся получает role="user" (повышение админ назначает вручную).

Правила, принятые заранее (см. описание Этапа 0/0.5):
  * срок действия 7 дней;
  * лимита использований нет — токен работает до истечения срока или отзыва;
  * отозвать можно в любой момент (revoked_at).

TenantMixin: админские эндпоинты видят только приглашения своей компании
(read-фильтр из src/db/tenant_scope.py). Поиск по токену при регистрации и в
боте идёт в сессии БЕЗ привязки к workspace — у человека, который ещё не
зарегистрирован, workspace пока неизвестен, он определяется самим токеном.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base
from src.models.mixins import TenantMixin


class WorkspaceInviteModel(TenantMixin, Base):
    __tablename__ = "workspace_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    # secrets.token_urlsafe(24) → 32 символа [A-Za-z0-9_-]; с префиксом "ws_"
    # укладывается в лимит Telegram на параметр deep link (64 символа).
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
