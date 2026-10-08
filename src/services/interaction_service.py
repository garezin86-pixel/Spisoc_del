# src/services/interaction_service.py
from datetime import datetime, timezone

import structlog
from fastapi import HTTPException

from src.models.client import ClientModel
from src.models.interaction import InteractionModel
from src.models.user import UserModel, UserRole
from src.repositories.client_repository import ClientRepository
from src.repositories.interaction_repository import InteractionRepository
from src.schemas.interaction import InteractionCreate, InteractionUpdate

logger = structlog.get_logger()

_PROCESS_FIELDS = ("type", "occurred_at")  # влияют на процесс: от них считается «последний контакт»


def _is_manager(user: UserModel) -> bool:
    return user.role in (UserRole.admin, UserRole.manager)


def _same(field: str, current, new) -> bool:
    if field == "type":
        return current == getattr(new, "value", new)
    if field == "occurred_at":
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current == new
    return current == new


class InteractionService:
    """Сервис взаимодействий с клиентом.

    Правила доступа:
    - Читать: все пользователи компании.
    - Создавать: admin, manager и ответственный за клиента (автор — текущий пользователь).
    - Справочные поля (summary, contact_id): автор записи, ответственный за клиента, admin, manager.
    - Процессные поля (type, occurred_at) после создания: только admin и manager.
    - Удалять (мягко): только admin и manager — удаление сдвигает «последний контакт».
    Чужой клиент/запись (другая компания) неотличимы от несуществующих: 404.
    """

    def __init__(self, client_repo: ClientRepository, interaction_repo: InteractionRepository):
        self.client_repo = client_repo
        self.interaction_repo = interaction_repo

    async def _client_or_404(self, client_id: int) -> ClientModel:
        client = await self.client_repo.get_by_id(client_id)
        if client is None:
            raise HTTPException(404, "Клиент не найден")
        return client

    @staticmethod
    def _is_client_editor(client: ClientModel, user: UserModel) -> bool:
        return _is_manager(user) or client.owner_id == user.id

    async def _require_contact_of_client(self, client_id: int, contact_id: int) -> None:
        if await self.client_repo.get_contact(client_id, contact_id) is None:
            raise HTTPException(404, "Контакт не найден")

    async def _get_or_404(self, client_id: int, interaction_id: int) -> InteractionModel:
        item = await self.interaction_repo.get(client_id, interaction_id)
        if item is None:
            raise HTTPException(404, "Взаимодействие не найдено")
        return item

    async def list_interactions(self, client_id: int, offset: int, limit: int):
        await self._client_or_404(client_id)
        return await self.interaction_repo.list_for_client(client_id, offset, limit)

    async def create(self, client_id: int, data: InteractionCreate, current_user: UserModel) -> InteractionModel:
        client = await self._client_or_404(client_id)
        if not self._is_client_editor(client, current_user):
            raise HTTPException(403, "Добавлять взаимодействия могут admin, manager и ответственный за клиента")
        if data.contact_id is not None:
            await self._require_contact_of_client(client_id, data.contact_id)
        self.interaction_repo.set_audit_user(current_user.id)

        item = InteractionModel(
            client_id=client_id,
            contact_id=data.contact_id,
            type=data.type.value,
            occurred_at=data.occurred_at or datetime.now(timezone.utc),
            summary=data.summary,
            author_id=current_user.id,
        )
        created = await self.interaction_repo.create(item)
        await logger.ainfo("interaction_created", interaction_id=created.id, client_id=client_id)
        return created

    async def update(
        self, client_id: int, interaction_id: int, data: InteractionUpdate, current_user: UserModel
    ) -> InteractionModel:
        client = await self._client_or_404(client_id)
        item = await self._get_or_404(client_id, interaction_id)
        if not (self._is_client_editor(client, current_user) or item.author_id == current_user.id):
            raise HTTPException(403, "Править может автор, ответственный за клиента, admin или manager")

        changes = data.model_dump(exclude_unset=True)
        if not _is_manager(current_user):
            changed_process = [
                f for f in _PROCESS_FIELDS if f in changes and not _same(f, getattr(item, f), changes[f])
            ]
            if changed_process:
                raise HTTPException(403, "Менять тип и дату взаимодействия могут только admin и manager")
        if changes.get("contact_id") is not None:
            await self._require_contact_of_client(client_id, changes["contact_id"])
        self.interaction_repo.set_audit_user(current_user.id)

        for field, value in changes.items():
            setattr(item, field, value.value if field == "type" else value)

        updated = await self.interaction_repo.update(item)
        await logger.ainfo("interaction_updated", interaction_id=interaction_id, client_id=client_id)
        return updated

    async def delete(self, client_id: int, interaction_id: int, current_user: UserModel) -> dict:
        await self._client_or_404(client_id)
        item = await self._get_or_404(client_id, interaction_id)
        if not _is_manager(current_user):
            raise HTTPException(403, "Удалять взаимодействия могут только admin и manager")
        self.interaction_repo.set_audit_user(current_user.id)

        await self.interaction_repo.soft_delete(item)
        await logger.ainfo("interaction_deleted", interaction_id=interaction_id, client_id=client_id)
        return {"message": f"Interaction {interaction_id} deleted"}
