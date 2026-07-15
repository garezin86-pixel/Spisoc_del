# src/services/push_service.py
import asyncio
import json

import structlog
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

from src.core.config import VAPID_CLAIMS_EMAIL, VAPID_PRIVATE_KEY
from src.models.push_subscription import PushSubscriptionModel
from src.models.user import UserModel
from src.repositories.push_repository import PushRepository
from src.schemas.push_subscription import PushSubscriptionCreate

logger = structlog.get_logger()

# ВАЖНО: строим Vapid-объект ОДИН РАЗ из PEM при первом использовании, а не
# передаём VAPID_PRIVATE_KEY как сырую строку в webpush() на каждый вызов.
#
# Причина: если pywebpush.webpush() получает vapid_private_key строкой (не
# объектом Vapid), он внутри себя вызывает Vapid.from_string(), который
# устроен так: убирает переносы строк и пытается декодировать ВЕСЬ результат
# как base64url. Для настоящего PEM (с "-----BEGIN PRIVATE KEY-----" и
# "-----END PRIVATE KEY-----" в начале/конце) это ломается — сами маркеры
# BEGIN/END не являются валидным base64, и cryptography падает с
# "ASN.1 parsing error: invalid length". Vapid.from_pem() же корректно
# отрезает первую/последнюю строку PEM перед декодированием.
_vapid_instance: Vapid | None = None


def _get_vapid() -> Vapid:
    global _vapid_instance
    if _vapid_instance is None:
        if not VAPID_PRIVATE_KEY:
            raise RuntimeError("VAPID_PRIVATE_KEY не настроен — push отправить нельзя")
        _vapid_instance = Vapid.from_pem(VAPID_PRIVATE_KEY.encode())
    return _vapid_instance


class PushService:
    def __init__(self, push_repo: PushRepository):
        self.push_repo = push_repo

    async def subscribe(self, user: UserModel, data: PushSubscriptionCreate) -> PushSubscriptionModel:
        return await self.push_repo.create_or_update(
            user_id=user.id,
            endpoint=data.endpoint,
            p256dh_key=data.keys.p256dh,
            auth_key=data.keys.auth,
        )

    async def unsubscribe(self, user: UserModel, endpoint: str) -> dict:
        subscription = await self.push_repo.get_by_endpoint(endpoint)
        # Тихо игнорируем чужой/несуществующий endpoint — отписка должна
        # быть идемпотентной (повторный клик "выключить push" не должен падать).
        if subscription and subscription.user_id == user.id:
            await self.push_repo.delete(subscription)
        return {"message": "unsubscribed"}

    async def list_subscriptions(self, user: UserModel) -> list[PushSubscriptionModel]:
        return await self.push_repo.list_for_user(user.id)


def _send_push_sync(subscription_info: dict, payload: dict) -> None:
    """
    Синхронный вызов pywebpush — выполняется в отдельном потоке через
    asyncio.to_thread, чтобы не блокировать event loop (pywebpush использует
    requests, не httpx/aiohttp).
    """
    webpush(
        subscription_info=subscription_info,
        data=json.dumps(payload),
        vapid_private_key=_get_vapid(),
        vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"},
    )


async def send_push_to_user(
    push_repo: PushRepository,
    user_id: int,
    title: str,
    body: str,
    url: str | None = None,
) -> int:
    """
    Отправляет push всем активным подпискам пользователя (может быть
    несколько устройств/браузеров одновременно). Возвращает число успешных
    отправок. Просроченные/отозванные подписки (404/410 от push-сервиса
    браузера — пользователь удалил приложение, очистил данные сайта и т.п.)
    автоматически удаляются, чтобы не пытаться слать в никуда бесконечно.

    Best-effort: ошибки отправки не пробрасываются наружу — push всегда
    дополнительный канал поверх Telegram/WebSocket, а не единственный.
    """
    if not VAPID_PRIVATE_KEY:
        return 0  # push не настроен на этом деплое — тихо ничего не делаем

    subscriptions = await push_repo.list_for_user(user_id)
    if not subscriptions:
        return 0

    payload = {"title": title, "body": body, "url": url or "/"}
    sent = 0

    for sub in subscriptions:
        subscription_info = {
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key},
        }
        try:
            await asyncio.to_thread(_send_push_sync, subscription_info, payload)
            sent += 1
        except WebPushException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in (404, 410):
                # Подписка больше не существует на стороне push-сервиса браузера
                await push_repo.delete(sub)
                await logger.ainfo("push_subscription_expired_removed", subscription_id=sub.id)
            else:
                await logger.awarning("push_send_failed", subscription_id=sub.id, error=str(exc))
        except Exception as exc:
            await logger.awarning("push_send_failed", subscription_id=sub.id, error=str(exc))

    return sent
