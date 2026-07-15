# src/repositories/push_repository.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.push_subscription import PushSubscriptionModel


class PushRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_endpoint(self, endpoint: str) -> PushSubscriptionModel | None:
        result = await self.session.execute(
            select(PushSubscriptionModel).where(PushSubscriptionModel.endpoint == endpoint)
        )
        return result.scalar_one_or_none()

    async def create_or_update(
        self, user_id: int, endpoint: str, p256dh_key: str, auth_key: str
    ) -> PushSubscriptionModel:
        """
        Идемпотентно: если тот же endpoint уже подписан (например, повторная
        подписка того же браузера после переустановки Service Worker),
        обновляем ключи вместо создания дубликата — endpoint уникален.
        """
        existing = await self.get_by_endpoint(endpoint)
        if existing:
            existing.user_id = user_id
            existing.p256dh_key = p256dh_key
            existing.auth_key = auth_key
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        subscription = PushSubscriptionModel(
            user_id=user_id, endpoint=endpoint, p256dh_key=p256dh_key, auth_key=auth_key
        )
        self.session.add(subscription)
        await self.session.commit()
        await self.session.refresh(subscription)
        return subscription

    async def list_for_user(self, user_id: int) -> list[PushSubscriptionModel]:
        result = await self.session.execute(
            select(PushSubscriptionModel).where(PushSubscriptionModel.user_id == user_id)
        )
        return list(result.scalars().all())

    async def delete_by_endpoint(self, endpoint: str) -> bool:
        subscription = await self.get_by_endpoint(endpoint)
        if not subscription:
            return False
        await self.session.delete(subscription)
        await self.session.commit()
        return True

    async def delete(self, subscription: PushSubscriptionModel) -> None:
        await self.session.delete(subscription)
        await self.session.commit()
