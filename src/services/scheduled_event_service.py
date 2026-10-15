# src/services/scheduled_event_service.py
from datetime import datetime, timezone

import structlog
from fastapi import HTTPException

from src.models.client import ClientModel
from src.models.interaction import InteractionModel
from src.models.scheduled_event import EventStatus, ScheduledEventModel
from src.models.user import UserModel, UserRole
from src.repositories.client_repository import ClientRepository
from src.repositories.scheduled_event_repository import ScheduledEventRepository
from src.repositories.users_repository import UserRepository
from src.schemas.scheduled_event import EventComplete, EventCreate, EventSchema, EventUpdate

logger = structlog.get_logger()


def _is_manager(user: UserModel) -> bool:
    return user.role in (UserRole.admin, UserRole.manager)


class ScheduledEventService:
    """Сервис запланированных встреч и звонков.

    Правила доступа:
    - Читать: все пользователи компании.
    - Создавать: admin, manager и ответственный за клиента (ответственный за событие — любой сотрудник компании,
      по умолчанию автор).
    - Менять (время, ответственного, статус planned/cancelled, текст) и завершать: admin, manager и ответственный
      за событие.
    - Удалять (мягко): только admin и manager.
    - Состоявшееся событие (done) не меняется и не завершается повторно: 409.
    Чужой клиент/событие (другая компания) неотличимы от несуществующих: 404.
    """

    def __init__(
        self,
        client_repo: ClientRepository,
        event_repo: ScheduledEventRepository,
        user_repo: UserRepository,
    ):
        self.client_repo = client_repo
        self.event_repo = event_repo
        self.user_repo = user_repo

    async def _client_or_404(self, client_id: int) -> ClientModel:
        client = await self.client_repo.get_by_id(client_id)
        if client is None:
            raise HTTPException(404, "Клиент не найден")
        return client

    async def _event_or_404(self, event_id: int) -> ScheduledEventModel:
        event = await self.event_repo.get(event_id)
        if event is None:
            raise HTTPException(404, "Событие не найдено")
        return event

    async def _require_contact_of_client(self, client_id: int, contact_id: int) -> None:
        if await self.client_repo.get_contact(client_id, contact_id) is None:
            raise HTTPException(404, "Контакт не найден")

    async def _require_user_exists(self, user_id: int) -> None:
        if await self.user_repo.get_by_id(user_id) is None:
            raise HTTPException(404, "Пользователь не найден")

    @staticmethod
    def _require_editor(event: ScheduledEventModel, user: UserModel) -> None:
        if not (_is_manager(user) or event.assignee_id == user.id):
            raise HTTPException(403, "Менять событие может ответственный за него, admin или manager")

    @staticmethod
    def _require_planned(event: ScheduledEventModel) -> None:
        if event.status == EventStatus.done.value:
            raise HTTPException(409, "Событие уже состоялось")

    async def _to_schemas(self, events: list[ScheduledEventModel]) -> list[EventSchema]:
        """Схемы ответа с названием клиента (одним запросом на все события)."""
        names = await self.event_repo.client_names({e.client_id for e in events})
        return [
            EventSchema.model_validate(e).model_copy(update={"client_name": names.get(e.client_id)}) for e in events
        ]

    async def _to_schema(self, event: ScheduledEventModel) -> EventSchema:
        return (await self._to_schemas([event]))[0]

    async def list_events(self, **filters) -> tuple[list[EventSchema], int]:
        if filters.get("client_id") is not None:
            await self._client_or_404(filters["client_id"])
        items, total = await self.event_repo.list_events(**filters)
        return await self._to_schemas(items), total

    async def create(self, client_id: int, data: EventCreate, current_user: UserModel) -> EventSchema:
        client = await self._client_or_404(client_id)
        if not (_is_manager(current_user) or client.owner_id == current_user.id):
            raise HTTPException(403, "Планировать события могут admin, manager и ответственный за клиента")
        if data.contact_id is not None:
            await self._require_contact_of_client(client_id, data.contact_id)
        assignee_id = data.assignee_id if data.assignee_id is not None else current_user.id
        if assignee_id != current_user.id:
            await self._require_user_exists(assignee_id)
        self.event_repo.set_audit_user(current_user.id)

        event = ScheduledEventModel(
            client_id=client_id,
            contact_id=data.contact_id,
            type=data.type.value,
            title=data.title,
            starts_at=data.starts_at,
            duration_minutes=data.duration_minutes,
            assignee_id=assignee_id,
            status=EventStatus.planned.value,
            notes=data.notes,
            created_by_id=current_user.id,
        )
        created = await self.event_repo.create(event)
        await logger.ainfo("scheduled_event_created", event_id=created.id, client_id=client_id)
        return await self._to_schema(created)

    async def update(self, event_id: int, data: EventUpdate, current_user: UserModel) -> EventSchema:
        event = await self._event_or_404(event_id)
        self._require_editor(event, current_user)
        self._require_planned(event)

        changes = data.model_dump(exclude_unset=True)
        if changes.get("contact_id") is not None:
            await self._require_contact_of_client(event.client_id, changes["contact_id"])
        if changes.get("assignee_id") is not None and changes["assignee_id"] != event.assignee_id:
            await self._require_user_exists(changes["assignee_id"])
        self.event_repo.set_audit_user(current_user.id)

        reschedule = "starts_at" in changes and changes["starts_at"] != event.starts_at
        reopen = changes.get("status") == EventStatus.planned and event.status == EventStatus.cancelled.value
        for field, value in changes.items():
            setattr(event, field, value.value if field in ("type", "status") else value)
        if reschedule or reopen:
            event.reminded_at = None  # новое время / событие вернули в работу — новое напоминание

        updated = await self.event_repo.update(event)
        await logger.ainfo("scheduled_event_updated", event_id=event_id)
        return await self._to_schema(updated)

    async def complete(self, event_id: int, data: EventComplete, current_user: UserModel) -> EventSchema:
        event = await self._event_or_404(event_id)
        self._require_editor(event, current_user)
        self._require_planned(event)
        if event.status == EventStatus.cancelled.value:
            raise HTTPException(409, "Событие отменено: сначала верните его в planned")
        self.event_repo.set_audit_user(current_user.id)

        interaction = InteractionModel(
            client_id=event.client_id,
            contact_id=event.contact_id,
            type=event.type,
            occurred_at=datetime.now(timezone.utc),
            summary=data.summary or event.notes,
            author_id=current_user.id,
        )
        completed = await self.event_repo.complete(event, interaction)
        await logger.ainfo("scheduled_event_completed", event_id=event_id, interaction_id=interaction.id)
        return await self._to_schema(completed)

    async def delete(self, event_id: int, current_user: UserModel) -> dict:
        event = await self._event_or_404(event_id)
        if not _is_manager(current_user):
            raise HTTPException(403, "Удалять события могут только admin и manager")
        self.event_repo.set_audit_user(current_user.id)

        await self.event_repo.soft_delete(event)
        await logger.ainfo("scheduled_event_deleted", event_id=event_id)
        return {"message": f"Event {event_id} deleted"}
