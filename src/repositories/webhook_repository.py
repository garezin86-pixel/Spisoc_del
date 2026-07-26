# src/repositories/webhook_repository.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.webhook import WebhookModel


class WebhookRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_id: int,
        url: str,
        secret: str,
        secret_prefix: str,
        events: list[str],
        is_active: bool,
    ) -> WebhookModel:
        webhook = WebhookModel(
            user_id=user_id,
            url=url,
            secret=secret,
            secret_prefix=secret_prefix,
            events=events,
            is_active=is_active,
        )
        self.session.add(webhook)
        await self.session.commit()
        await self.session.refresh(webhook)
        return webhook

    async def list_for_user(self, user_id: int) -> list[WebhookModel]:
        result = await self.session.execute(
            select(WebhookModel).where(WebhookModel.user_id == user_id).order_by(WebhookModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, webhook_id: int) -> WebhookModel | None:
        return await self.session.get(WebhookModel, webhook_id)

    async def get_active_for_users(self, user_ids: list[int]) -> list[WebhookModel]:
        """
        Все активные вебхуки для набора пользователей (без фильтра по событию —
        фильтрация по event делается в дальнейшем на стороне вызывающего кода,
        т.к. JSON-containment операторы различаются между Postgres и SQLite,
        а вебхуков на одного пользователя обычно единицы — фильтровать в
        Python дешевле, чем городить кросс-БД SQL).
        """
        if not user_ids:
            return []
        result = await self.session.execute(
            select(WebhookModel).where(
                WebhookModel.user_id.in_(user_ids),
                WebhookModel.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def save(self, webhook: WebhookModel) -> None:
        """Сохраняет изменения, внесённые напрямую в атрибуты инстанса."""
        self.session.add(webhook)
        await self.session.commit()

    async def update(self, webhook: WebhookModel, **fields) -> WebhookModel:
        for key, value in fields.items():
            if value is not None:
                setattr(webhook, key, value)
        await self.session.commit()
        await self.session.refresh(webhook)
        return webhook

    async def delete(self, webhook: WebhookModel) -> None:
        await self.session.delete(webhook)
        await self.session.commit()
