# src/services/webhook_dispatcher.py
"""
Доставка исходящих вебхуков.

Два режима использования:
- dispatch_webhook_event(...) — вызывается из роутеров/сервисов при реальных
  событиях (создание/смена статуса/удаление задачи, комментарий). Fire-and-
  forget: планирует доставку в фоне (asyncio.create_task) и не блокирует
  HTTP-ответ пользователю — чужой сервер может отвечать секундами или не
  отвечать вовсе, и это не должно замедлять основной API.
- deliver_test_event(...) — синхронная (await'-ится) разовая тестовая
  отправка из ручки "Отправить тестовое событие", чтобы пользователь сразу
  увидел результат в UI.
"""

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import structlog

from src.db import get_session_maker
from src.models.enums import WebhookEvent
from src.repositories.webhook_repository import WebhookRepository

logger = structlog.get_logger()

WEBHOOK_TIMEOUT_SECONDS = 5.0
# После стольки подряд неудачных доставок вебхук автоматически отключается —
# намертво умерший endpoint иначе долбился бы при каждом событии бесконечно.
MAX_CONSECUTIVE_FAILURES = 10


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _build_body(event: str, payload: dict) -> bytes:
    envelope = {
        "event": event,
        "data": payload,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8")


async def _post(url: str, secret: str, event: str, body: bytes) -> tuple[int | None, str | None]:
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Event": event,
        "X-Webhook-Signature": f"sha256={_sign(secret, body)}",
    }
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(url, content=body, headers=headers)
            return response.status_code, None
    except httpx.HTTPError as exc:
        return None, str(exc)[:500]


async def deliver_test_event(url: str, secret: str) -> tuple[int | None, str | None]:
    """Разовая синхронная тестовая доставка — не трогает failure_count/is_active."""
    body = _build_body("webhook.test", {"message": "Тестовое событие из Spisok Del"})
    return await _post(url, secret, "webhook.test", body)


async def _dispatch_and_record(event: str, user_ids: list[int], payload: dict) -> None:
    session_maker = get_session_maker()
    async with session_maker() as session:
        repo = WebhookRepository(session)
        webhooks = await repo.get_active_for_users(user_ids)
        matching = [w for w in webhooks if event in (w.events or [])]
        if not matching:
            return

        body = _build_body(event, payload)
        for webhook in matching:
            status_code, error = await _post(webhook.url, webhook.secret, event, body)
            webhook.last_triggered_at = datetime.now(timezone.utc)
            webhook.last_status_code = status_code
            webhook.last_error = error

            failed = error is not None or (status_code is not None and status_code >= 400)
            if failed:
                webhook.failure_count += 1
                if webhook.failure_count >= MAX_CONSECUTIVE_FAILURES:
                    webhook.is_active = False
                    await logger.awarning(
                        "webhook_auto_disabled",
                        webhook_id=webhook.id,
                        url=webhook.url,
                        failure_count=webhook.failure_count,
                    )
            else:
                webhook.failure_count = 0

            await repo.save(webhook)


def _schedule(coro) -> asyncio.Task:
    """
    Обёртка над asyncio.create_task — существует отдельной функцией специально
    для тестов: monkeypatch.setattr(webhook_dispatcher, "_schedule", ...)
    подменяет планирование ТОЛЬКО для вебхуков, не трогая глобальный
    asyncio.create_task (который использует остальной код приложения,
    например уведомления о повторяющихся задачах в task_service.py).
    """
    return asyncio.create_task(coro)


def dispatch_webhook_event(event: WebhookEvent, user_ids: list[int], payload: dict) -> None:
    """
    Планирует доставку в фоне. Best-effort и не бросает исключений наружу —
    вебхуки всегда дополнительный канал поверх основной логики API, а не
    то, от чего зависит успешность основного запроса.
    """
    if not user_ids:
        return
    try:
        _schedule(_dispatch_and_record(event.value, list(set(user_ids)), payload))
    except RuntimeError:
        # Нет активного event loop (например, вызвано вне запроса/теста без
        # loop) — тихо пропускаем, это никогда не должно ронять основной поток.
        pass
