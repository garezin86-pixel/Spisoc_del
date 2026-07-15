# src/models/push_subscription.py
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base

if TYPE_CHECKING:
    from src.models.user import UserModel


class PushSubscriptionModel(Base):
    """
    Подписка браузера на веб-push уведомления (Push API + Service Worker).

    Один пользователь может иметь НЕСКОЛЬКО подписок одновременно — открыл
    приложение с телефона и с рабочего ноутбука, оба должны получать пуши.
    endpoint уникален для каждой пары (браузер, устройство) — это URL push-
    сервиса конкретного браузера (FCM для Chrome, Mozilla push для Firefox
    и т.д.), выданный при подписке через navigator.serviceWorker.pushManager.
    """

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh_key: Mapped[str] = mapped_column(String(200), nullable=False)
    auth_key: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["UserModel"] = relationship("UserModel", back_populates="push_subscriptions")
