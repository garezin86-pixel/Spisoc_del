# src/models/webhook.py
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base

if TYPE_CHECKING:
    from src.models.user import UserModel

# JSONB на PostgreSQL (продакшн), обычный JSON на SQLite (тесты/локально) —
# тот же паттерн, что и в src/models/audit.py.
_JSONVariant = JSONB().with_variant(JSON(), "sqlite")


class WebhookModel(Base):
    """
    Исходящий вебхук — противоположность PAT-токену. PAT — это «извне
    достучаться до нас» (pull), вебхук — «уведомить внешнюю систему, когда
    у нас что-то произошло» (push), без постоянного опроса с их стороны.

    В отличие от PAT-токена, secret хранится в открытом виде, а не хэшем:
    сервер сам подписывает каждый исходящий запрос HMAC-SHA256 этим секретом
    (заголовок X-Webhook-Signature), чтобы получатель мог убедиться, что
    запрос действительно от нас, а не подделан — для этого секрет должен
    быть доступен серверу при каждой отправке, обратно его не восстановить
    из хэша. Держать секрет в секрете — забота получателя и деплоя, а не
    повод его хэшировать (тут не аутентификация ВХОДЯЩЕГО запроса, как у PAT).
    """

    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    secret: Mapped[str] = mapped_column(String(100), nullable=False)
    # Первые символы секрета — чтобы владелец опознал вебхук в списке, не
    # запрашивая секрет заново (аналог token_prefix у PersonalAccessTokenModel).
    secret_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    # Список значений WebhookEvent, например ["task.done", "comment.added"].
    events: Mapped[list[str]] = mapped_column(_JSONVariant, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Подряд идущих неудачных доставок. Сбрасывается в 0 при первой успешной.
    # После MAX_CONSECUTIVE_FAILURES (см. webhook_dispatcher.py) вебхук
    # автоматически отключается — чтобы намертво умерший endpoint не
    # долбился бесконечно при каждом событии.
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))

    user: Mapped["UserModel"] = relationship("UserModel", back_populates="webhooks")

    def __str__(self) -> str:
        return f"{self.url} ({self.secret_prefix}…)"
