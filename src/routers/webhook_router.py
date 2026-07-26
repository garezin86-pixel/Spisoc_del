# src/routers/webhook_router.py
from fastapi import APIRouter, Depends

from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.webhook_repository import WebhookRepository
from src.schemas.webhook import (
    WebhookCreate,
    WebhookCreatedResponse,
    WebhookSchema,
    WebhookSecretRotatedResponse,
    WebhookTestResult,
    WebhookUpdate,
)
from src.services.webhook_service import WebhookService

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def get_webhook_service(session: SessionDep) -> WebhookService:
    return WebhookService(WebhookRepository(session))


@router.get("", response_model=list[WebhookSchema])
async def list_webhooks(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    webhooks = await get_webhook_service(session).list_webhooks(current_user)
    return [WebhookService.to_schema(w) for w in webhooks]


@router.post(
    "",
    response_model=WebhookCreatedResponse,
    status_code=201,
    summary="Создать исходящий вебхук",
    description=(
        "Полный secret возвращается ТОЛЬКО в этом ответе — сохраните его сразу, "
        "повторно получить не получится (в базе хранится, но API его больше не отдаёт). "
        "Каждый запрос подписывается заголовком X-Webhook-Signature: sha256=<hmac>, "
        "посчитанным как HMAC-SHA256(secret, raw_body) — так получатель может "
        "убедиться, что запрос действительно от нас."
    ),
)
async def create_webhook(
    data: WebhookCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_webhook_service(session).create_webhook(current_user, data)


@router.patch("/{webhook_id}", response_model=WebhookSchema)
async def update_webhook(
    webhook_id: int,
    data: WebhookUpdate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    webhook = await get_webhook_service(session).update_webhook(current_user, webhook_id, data)
    return WebhookService.to_schema(webhook)


@router.delete("/{webhook_id}", response_model=dict)
async def delete_webhook(
    webhook_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_webhook_service(session).delete_webhook(current_user, webhook_id)


@router.post(
    "/{webhook_id}/rotate-secret",
    response_model=WebhookSecretRotatedResponse,
    summary="Перевыпустить secret",
    description="Если секрет утёк — генерирует новый без пересоздания вебхука (URL и подписки на события не меняются).",
)
async def rotate_secret(
    webhook_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_webhook_service(session).regenerate_secret(current_user, webhook_id)


@router.post(
    "/{webhook_id}/test",
    response_model=WebhookTestResult,
    summary="Отправить тестовое событие",
    description="Синхронно бьёт по настроенному URL синтетическим payload'ом, чтобы сразу проверить конфигурацию.",
)
async def test_webhook(
    webhook_id: int,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    return await get_webhook_service(session).send_test_event(current_user, webhook_id)
