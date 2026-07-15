# src/routers/push_router.py
from fastapi import APIRouter, Depends

from src.core.config import VAPID_PUBLIC_KEY
from src.core.dependencies import get_current_user
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.push_repository import PushRepository
from src.schemas.push_subscription import (
    PushSubscriptionCreate,
    PushSubscriptionSchema,
    PushSubscriptionUnsubscribe,
)
from src.services.push_service import PushService

router = APIRouter(prefix="/push", tags=["Web Push"])


@router.get("/vapid-public-key", response_model=dict)
async def get_vapid_public_key():
    """
    Публичный ключ для `pushManager.subscribe({applicationServerKey: ...})`
    на фронтенде. Не требует авторизации — это открытый ключ, его безопасно
    раздавать всем (в отличие от VAPID_PRIVATE_KEY, который никогда не
    покидает бэкенд).
    """
    return {"public_key": VAPID_PUBLIC_KEY}


@router.post("/subscribe", response_model=PushSubscriptionSchema, status_code=201)
async def subscribe(
    data: PushSubscriptionCreate,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    service = PushService(PushRepository(session))
    return await service.subscribe(current_user, data)


@router.post("/unsubscribe", response_model=dict)
async def unsubscribe(
    data: PushSubscriptionUnsubscribe,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    service = PushService(PushRepository(session))
    return await service.unsubscribe(current_user, data.endpoint)


@router.get("/subscriptions", response_model=list[PushSubscriptionSchema])
async def list_subscriptions(
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    service = PushService(PushRepository(session))
    return await service.list_subscriptions(current_user)
