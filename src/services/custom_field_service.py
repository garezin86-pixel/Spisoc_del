# src/services/custom_field_service.py
"""Свои поля клиентов и сделок (Smart Tables, этап 3).

Права:
  * поля (создать, переименовать, изменить список, удалить) — только admin и manager; читать могут все;
  * значения — как правка самой записи: клиента правят ответственный, admin, manager (ClientService),
    сделку — ответственный, admin, manager (DealService.update_deal).
Тип поля после создания не меняется (иначе потеряли бы смысл уже введённые значения).
Удаление поля мягкое: колонка исчезает из таблиц, значения остаются в базе.
"""

from typing import Any

import structlog
from fastapi import HTTPException

from src.models.custom_field import VALUE_COLUMN_BY_TYPE, CustomFieldModel, CustomFieldType, CustomFieldValueModel
from src.models.user import UserModel, UserRole
from src.repositories.client_repository import ClientRepository
from src.repositories.custom_field_repository import CustomFieldRepository
from src.repositories.deal_repository import DealRepository
from src.schemas.custom_field import CustomFieldCreate, CustomFieldUpdate, CustomValueSchema
from src.services.value_coercion import coerce_value

logger = structlog.get_logger()

MAX_FIELDS_PER_ENTITY = 30


def _is_manager(user: UserModel) -> bool:
    return user.role in (UserRole.admin, UserRole.manager)


class CustomFieldService:
    def __init__(self, field_repo: CustomFieldRepository, client_repo: ClientRepository, deal_repo: DealRepository):
        self.field_repo = field_repo
        self.client_repo = client_repo
        self.deal_repo = deal_repo

    # ── поля ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _require_manager(user: UserModel) -> None:
        if not _is_manager(user):
            raise HTTPException(403, "Управлять полями могут только admin и manager")

    async def _field_or_404(self, field_id: int) -> CustomFieldModel:
        field = await self.field_repo.get_field(field_id)
        if field is None:
            raise HTTPException(404, "Поле не найдено")
        return field

    async def _require_unique_name(self, entity_type: str, name: str, exclude_id: int | None = None) -> None:
        key = name.casefold()
        for other in await self.field_repo.list_fields([entity_type]):
            if other.id != exclude_id and other.name.casefold() == key:
                raise HTTPException(409, f"Поле «{other.name}» уже есть")

    async def list_fields(self, entity_type: str | None) -> list[CustomFieldModel]:
        return await self.field_repo.list_fields([entity_type] if entity_type else None)

    async def create_field(self, data: CustomFieldCreate, current_user: UserModel) -> CustomFieldModel:
        self._require_manager(current_user)
        existing = await self.field_repo.list_fields([data.entity_type])
        if len(existing) >= MAX_FIELDS_PER_ENTITY:
            raise HTTPException(409, f"Не больше {MAX_FIELDS_PER_ENTITY} своих полей на одну сущность")
        await self._require_unique_name(data.entity_type, data.name)
        self.field_repo.set_audit_user(current_user.id)
        field = CustomFieldModel(
            entity_type=data.entity_type,
            name=data.name,
            field_type=data.field_type,
            options=data.options,
            position=await self.field_repo.max_position(data.entity_type) + 1,
        )
        created = await self.field_repo.create_field(field)
        await logger.ainfo("custom_field_created", field_id=created.id, entity_type=created.entity_type)
        return created

    async def update_field(self, field_id: int, data: CustomFieldUpdate, current_user: UserModel) -> CustomFieldModel:
        self._require_manager(current_user)
        field = await self._field_or_404(field_id)
        changes = data.model_dump(exclude_unset=True)
        if "options" in changes and field.field_type != CustomFieldType.select.value:
            raise HTTPException(422, "Значения списка есть только у поля типа select")
        if "name" in changes:
            await self._require_unique_name(field.entity_type, changes["name"], exclude_id=field.id)
        self.field_repo.set_audit_user(current_user.id)
        for key, value in changes.items():
            setattr(field, key, value)
        updated = await self.field_repo.update_field(field)
        await logger.ainfo("custom_field_updated", field_id=field_id)
        return updated

    async def delete_field(self, field_id: int, current_user: UserModel) -> dict:
        self._require_manager(current_user)
        field = await self._field_or_404(field_id)
        self.field_repo.set_audit_user(current_user.id)
        await self.field_repo.soft_delete_field(field)
        await logger.ainfo("custom_field_deleted", field_id=field_id)
        return {"message": f"Custom field {field_id} deleted"}

    # ── значения ─────────────────────────────────────────────────────────────
    async def _require_can_edit_entity(self, field: CustomFieldModel, entity_id: int, user: UserModel) -> None:
        """Запись должна существовать (своя компания, не удалена); значения правят те же, кто правит саму запись."""
        if field.entity_type == "client":
            client = await self.client_repo.get_by_id(entity_id)
            if client is None:
                raise HTTPException(404, "Клиент не найден")
            owner_id = client.owner_id
        else:
            deal = await self.deal_repo.get_deal(entity_id)
            if deal is None:
                raise HTTPException(404, "Сделка не найдена")
            owner_id = deal.owner_id
        if not (_is_manager(user) or owner_id == user.id):
            raise HTTPException(403, "Править значения может ответственный, admin или manager")

    @staticmethod
    def _coerce(field: CustomFieldModel, raw: Any) -> Any:
        """Приводит значение к типу поля. None — очистка. Неверное значение — 422 (правила — value_coercion)."""
        return coerce_value(field.name, field.field_type, field.options, raw)

    async def list_values(self, entity_type: str, entity_id: int) -> list[CustomValueSchema]:
        """Заполненные значения записи (пустые не возвращаются)."""
        return [
            CustomValueSchema(field_id=field.id, entity_id=entity_id, value=row.value_for(field.field_type))
            for field, row in await self.field_repo.list_values(entity_type, entity_id)
            if row.value_for(field.field_type) is not None
        ]

    async def set_value(
        self, field_id: int, entity_id: int, raw_value: Any, current_user: UserModel
    ) -> CustomValueSchema:
        field = await self._field_or_404(field_id)
        await self._require_can_edit_entity(field, entity_id, current_user)
        value = self._coerce(field, raw_value)
        column = VALUE_COLUMN_BY_TYPE[field.field_type]

        self.field_repo.set_audit_user(current_user.id)
        row = await self.field_repo.get_value(field_id, entity_id)
        if row is None:
            if value is None:
                return CustomValueSchema(field_id=field_id, entity_id=entity_id, value=None)  # очищать нечего
            row = CustomFieldValueModel(field_id=field_id, entity_id=entity_id)
        setattr(row, column, value)
        saved = await self.field_repo.save_value(row)
        await logger.ainfo("custom_value_set", field_id=field_id, entity_id=entity_id, user_id=current_user.id)
        return CustomValueSchema(field_id=field_id, entity_id=entity_id, value=saved.value_for(field.field_type))
