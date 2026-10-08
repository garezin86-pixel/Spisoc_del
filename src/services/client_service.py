# src/services/client_service.py
import structlog
from fastapi import HTTPException

from src.models.client import ClientModel, ContactModel
from src.models.user import UserModel, UserRole
from src.repositories.client_repository import ClientRepository
from src.repositories.users_repository import UserRepository
from src.schemas.client import ClientCreate, ClientUpdate, ContactCreate, ContactUpdate

logger = structlog.get_logger()


def _is_manager(user: UserModel) -> bool:
    return user.role in (UserRole.admin, UserRole.manager)


class ClientService:
    """Сервис клиентов и контактов.

    Правила доступа:
    - Читать клиентов и контакты могут все пользователи компании.
    - Создавать клиента: admin и manager.
    - Править клиента и вести его контакты: admin, manager и ответственный за клиента.
    - Менять ответственного (owner_id): только admin и manager.
    - Удалять клиента: admin и manager (мягко, вместе с контактами).

    Чужой клиент (другая компания) неотличим от несуществующего: 404.
    """

    def __init__(self, client_repo: ClientRepository, user_repo: UserRepository):
        self.client_repo = client_repo
        self.user_repo = user_repo

    # ── проверки ─────────────────────────────────────────────────────────────
    @staticmethod
    def _require_manager(user: UserModel, detail: str) -> None:
        if not _is_manager(user):
            raise HTTPException(403, detail)

    @staticmethod
    def _require_can_edit(client: ClientModel, user: UserModel) -> None:
        if _is_manager(user) or client.owner_id == user.id:
            return
        raise HTTPException(403, "Править клиента могут admin, manager и ответственный за клиента")

    async def _require_owner_exists(self, owner_id: int) -> None:
        # get_by_id идёт через scoped-сессию: пользователь другой компании → None.
        if await self.user_repo.get_by_id(owner_id) is None:
            raise HTTPException(404, "Пользователь не найден")

    async def _get_client_or_404(self, client_id: int) -> ClientModel:
        client = await self.client_repo.get_by_id(client_id)
        if client is None:
            raise HTTPException(404, "Клиент не найден")
        return client

    # ── клиенты ──────────────────────────────────────────────────────────────
    async def create_client(self, data: ClientCreate, current_user: UserModel) -> ClientModel:
        self._require_manager(current_user, "Создавать клиентов могут admin и manager")
        self.client_repo.set_audit_user(current_user.id)

        owner_id = data.owner_id if data.owner_id is not None else current_user.id
        if data.owner_id is not None:
            await self._require_owner_exists(owner_id)

        client = ClientModel(
            name=data.name,
            phone=data.phone,
            email=data.email,
            address=data.address,
            notes=data.notes,
            owner_id=owner_id,
        )
        created = await self.client_repo.create(client)
        await logger.ainfo("client_created", client_id=created.id, user_id=current_user.id)
        return created

    async def get_clients(self, search: str | None, offset: int, limit: int) -> tuple[list[ClientModel], int]:
        return await self.client_repo.list_clients(search, offset, limit)

    async def get_client(self, client_id: int) -> ClientModel:
        return await self._get_client_or_404(client_id)

    async def update_client(self, client_id: int, data: ClientUpdate, current_user: UserModel) -> ClientModel:
        client = await self._get_client_or_404(client_id)
        self._require_can_edit(client, current_user)
        self.client_repo.set_audit_user(current_user.id)

        changes = data.model_dump(exclude_unset=True)
        if "owner_id" in changes:
            if not _is_manager(current_user):
                raise HTTPException(403, "Менять ответственного может только admin или manager")
            if changes["owner_id"] is not None:
                await self._require_owner_exists(changes["owner_id"])

        for field, value in changes.items():
            setattr(client, field, value)

        updated = await self.client_repo.update(client)
        await logger.ainfo("client_updated", client_id=client_id, user_id=current_user.id)
        return updated

    async def delete_client(self, client_id: int, current_user: UserModel) -> dict:
        client = await self._get_client_or_404(client_id)
        self._require_manager(current_user, "Удалять клиентов могут admin и manager")
        self.client_repo.set_audit_user(current_user.id)

        await self.client_repo.soft_delete(client)
        await logger.ainfo("client_deleted", client_id=client_id, user_id=current_user.id)
        return {"message": f"Client {client_id} deleted"}

    # ── контакты ─────────────────────────────────────────────────────────────
    async def get_contacts(self, client_id: int) -> list[ContactModel]:
        await self._get_client_or_404(client_id)
        return await self.client_repo.list_contacts(client_id)

    async def create_contact(self, client_id: int, data: ContactCreate, current_user: UserModel) -> ContactModel:
        client = await self._get_client_or_404(client_id)
        self._require_can_edit(client, current_user)
        self.client_repo.set_audit_user(current_user.id)

        contact = ContactModel(
            client_id=client_id,
            name=data.name,
            position=data.position,
            phone=data.phone,
            email=data.email,
            notes=data.notes,
        )
        created = await self.client_repo.create_contact(contact)
        await logger.ainfo("contact_created", contact_id=created.id, client_id=client_id, user_id=current_user.id)
        return created

    async def _get_contact_or_404(self, client_id: int, contact_id: int) -> ContactModel:
        contact = await self.client_repo.get_contact(client_id, contact_id)
        if contact is None:
            raise HTTPException(404, "Контакт не найден")
        return contact

    async def update_contact(
        self, client_id: int, contact_id: int, data: ContactUpdate, current_user: UserModel
    ) -> ContactModel:
        client = await self._get_client_or_404(client_id)
        self._require_can_edit(client, current_user)
        contact = await self._get_contact_or_404(client_id, contact_id)
        self.client_repo.set_audit_user(current_user.id)

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(contact, field, value)

        updated = await self.client_repo.update_contact(contact)
        await logger.ainfo("contact_updated", contact_id=contact_id, client_id=client_id, user_id=current_user.id)
        return updated

    async def delete_contact(self, client_id: int, contact_id: int, current_user: UserModel) -> dict:
        client = await self._get_client_or_404(client_id)
        self._require_can_edit(client, current_user)
        contact = await self._get_contact_or_404(client_id, contact_id)
        self.client_repo.set_audit_user(current_user.id)

        await self.client_repo.soft_delete_contact(contact)
        await logger.ainfo("contact_deleted", contact_id=contact_id, client_id=client_id, user_id=current_user.id)
        return {"message": f"Contact {contact_id} deleted"}
