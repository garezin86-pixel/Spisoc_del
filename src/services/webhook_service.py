# src/services/webhook_service.py
import secrets

from src.core.exceptions import not_found
from src.models.enums import WebhookEvent
from src.models.user import UserModel
from src.models.webhook import WebhookModel
from src.repositories.webhook_repository import WebhookRepository
from src.schemas.webhook import (
    WebhookCreate,
    WebhookCreatedResponse,
    WebhookSchema,
    WebhookSecretRotatedResponse,
    WebhookTestResult,
    WebhookUpdate,
)
from src.services.webhook_dispatcher import deliver_test_event

SECRET_PREFIX = "whsec_"


def _generate_secret() -> tuple[str, str]:
    """Возвращает (полный_секрет, префикс_для_отображения)."""
    secret = f"{SECRET_PREFIX}{secrets.token_urlsafe(32)}"
    prefix = secret[: len(SECRET_PREFIX) + 6]
    return secret, prefix


class WebhookService:
    def __init__(self, webhook_repo: WebhookRepository):
        self.webhook_repo = webhook_repo

    async def create_webhook(self, user: UserModel, data: WebhookCreate) -> WebhookCreatedResponse:
        secret, secret_prefix = _generate_secret()
        webhook = await self.webhook_repo.create(
            user_id=user.id,
            url=data.url,
            secret=secret,
            secret_prefix=secret_prefix,
            events=[e.value for e in data.events],
            is_active=data.is_active,
        )
        return WebhookCreatedResponse(
            id=webhook.id,
            url=webhook.url,
            secret_prefix=webhook.secret_prefix,
            events=[WebhookEvent(e) for e in webhook.events],
            is_active=webhook.is_active,
            created_at=webhook.created_at,
            last_triggered_at=webhook.last_triggered_at,
            last_status_code=webhook.last_status_code,
            last_error=webhook.last_error,
            failure_count=webhook.failure_count,
            secret=secret,
        )

    async def list_webhooks(self, user: UserModel) -> list[WebhookModel]:
        return await self.webhook_repo.list_for_user(user.id)

    async def _get_owned_or_404(self, user: UserModel, webhook_id: int) -> WebhookModel:
        webhook = await self.webhook_repo.get_by_id(webhook_id)
        # 404, а не 403, на чужой вебхук — чтобы не подтверждать перебором
        # ID, что вебхук с таким id вообще существует у кого-то другого.
        if not webhook or webhook.user_id != user.id:
            not_found("Вебхук не найден")
        return webhook

    async def update_webhook(self, user: UserModel, webhook_id: int, data: WebhookUpdate) -> WebhookModel:
        webhook = await self._get_owned_or_404(user, webhook_id)
        events = [e.value for e in data.events] if data.events is not None else None
        return await self.webhook_repo.update(
            webhook,
            url=data.url,
            events=events,
            is_active=data.is_active,
        )

    async def delete_webhook(self, user: UserModel, webhook_id: int) -> dict:
        webhook = await self._get_owned_or_404(user, webhook_id)
        await self.webhook_repo.delete(webhook)
        return {"message": "Вебхук удалён"}

    async def regenerate_secret(self, user: UserModel, webhook_id: int) -> WebhookSecretRotatedResponse:
        """Если секрет утёк — перевыпустить, не пересоздавая сам вебхук (те же события/URL)."""
        webhook = await self._get_owned_or_404(user, webhook_id)
        secret, secret_prefix = _generate_secret()
        webhook = await self.webhook_repo.update(webhook, secret=secret, secret_prefix=secret_prefix)
        return WebhookSecretRotatedResponse(id=webhook.id, secret=secret, secret_prefix=webhook.secret_prefix)

    async def send_test_event(self, user: UserModel, webhook_id: int) -> WebhookTestResult:
        """
        Бьёт по URL синтетическим payload'ом прямо сейчас (в отличие от
        реальных событий — синхронно, чтобы пользователь сразу увидел
        результат в UI, а не гадал, работает ли вообще настройка).
        """
        webhook = await self._get_owned_or_404(user, webhook_id)
        status_code, error = await deliver_test_event(webhook.url, webhook.secret)
        webhook.last_status_code = status_code
        webhook.last_error = error
        await self.webhook_repo.save(webhook)
        return WebhookTestResult(
            delivered=error is None and status_code is not None, status_code=status_code, error=error
        )

    @staticmethod
    def to_schema(webhook: WebhookModel) -> WebhookSchema:
        return WebhookSchema.model_validate(webhook)
