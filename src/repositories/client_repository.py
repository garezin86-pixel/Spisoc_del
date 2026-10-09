# src/repositories/client_repository.py
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.client import ClientModel, ContactModel
from src.models.deal import DealModel
from src.models.interaction import InteractionModel


def _like_pattern(text: str) -> str:
    """Экранирует % и _ в пользовательском поиске, чтобы они искались буквально."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class ClientRepository:
    """Репозиторий клиентов и контактов.

    Изоляция по компании — не здесь: к каждому ORM-запросу фильтр workspace_id
    добавляет слушатель из src/db/tenant_scope.py. Здесь только фильтр мягкого удаления.
    Поиск — ILIKE (а не GIN), чтобы он одинаково работал на Postgres и в тестах на SQLite.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    def set_audit_user(self, user_id: int | None) -> None:
        self.session.info["audit_user_id"] = user_id

    # ── клиенты ──────────────────────────────────────────────────────────────
    async def get_by_id(self, client_id: int) -> ClientModel | None:
        result = await self.session.execute(
            select(ClientModel).where(ClientModel.id == client_id, ClientModel.not_deleted_filter())
        )
        return result.scalar_one_or_none()

    async def list_clients(self, search: str | None, offset: int, limit: int) -> tuple[list[ClientModel], int]:
        query = select(ClientModel).where(ClientModel.not_deleted_filter())
        if search and search.strip():
            pattern = _like_pattern(search.strip())
            query = query.where(
                or_(
                    ClientModel.name.ilike(pattern, escape="\\"),
                    ClientModel.phone.ilike(pattern, escape="\\"),
                    ClientModel.email.ilike(pattern, escape="\\"),
                )
            )
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(
            query.order_by(func.lower(ClientModel.name), ClientModel.id).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def create(self, client: ClientModel) -> ClientModel:
        self.session.add(client)
        await self.session.commit()
        await self.session.refresh(client)
        return client

    async def update(self, client: ClientModel) -> ClientModel:
        await self.session.commit()
        await self.session.refresh(client)
        return client

    async def soft_delete(self, client: ClientModel) -> None:
        """Мягко удаляет клиента, его живые контакты и взаимодействия (одна транзакция, всё в аудите)."""
        interactions = await self.session.execute(
            select(InteractionModel).where(
                InteractionModel.client_id == client.id,
                InteractionModel.not_deleted_filter(),
            )
        )
        deals = await self.session.execute(
            select(DealModel).where(DealModel.client_id == client.id, DealModel.not_deleted_filter())
        )
        for interaction in interactions.scalars().all():
            interaction.soft_delete(self.session)
        for deal in deals.scalars().all():
            deal.soft_delete(self.session)
        for contact in await self.list_contacts(client.id):
            contact.soft_delete(self.session)
        client.soft_delete(self.session)
        await self.session.commit()

    # ── контакты ─────────────────────────────────────────────────────────────
    async def list_contacts(self, client_id: int) -> list[ContactModel]:
        result = await self.session.execute(
            select(ContactModel)
            .where(ContactModel.client_id == client_id, ContactModel.not_deleted_filter())
            .order_by(ContactModel.id)
        )
        return list(result.scalars().all())

    async def get_contact(self, client_id: int, contact_id: int) -> ContactModel | None:
        result = await self.session.execute(
            select(ContactModel).where(
                ContactModel.id == contact_id,
                ContactModel.client_id == client_id,
                ContactModel.not_deleted_filter(),
            )
        )
        return result.scalar_one_or_none()

    async def create_contact(self, contact: ContactModel) -> ContactModel:
        self.session.add(contact)
        await self.session.commit()
        await self.session.refresh(contact)
        return contact

    async def update_contact(self, contact: ContactModel) -> ContactModel:
        await self.session.commit()
        await self.session.refresh(contact)
        return contact

    async def soft_delete_contact(self, contact: ContactModel) -> None:
        contact.soft_delete(self.session)
        await self.session.commit()
