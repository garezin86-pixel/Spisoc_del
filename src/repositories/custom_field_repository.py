# src/repositories/custom_field_repository.py
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.custom_field import CustomFieldModel, CustomFieldValueModel


class CustomFieldRepository:
    """Репозиторий своих полей и их значений. Изоляция по компании — слушатель tenant_scope;
    здесь — мягкое удаление полей."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def set_audit_user(self, user_id: int | None) -> None:
        self.session.info["audit_user_id"] = user_id

    # ── поля ─────────────────────────────────────────────────────────────────
    async def list_fields(self, entity_types: Sequence[str] | None = None) -> list[CustomFieldModel]:
        query = select(CustomFieldModel).where(CustomFieldModel.not_deleted_filter())
        if entity_types is not None:
            query = query.where(CustomFieldModel.entity_type.in_(list(entity_types)))
        result = await self.session.execute(
            query.order_by(CustomFieldModel.entity_type, CustomFieldModel.position, CustomFieldModel.id)
        )
        return list(result.scalars().all())

    async def get_field(self, field_id: int) -> CustomFieldModel | None:
        result = await self.session.execute(
            select(CustomFieldModel).where(CustomFieldModel.id == field_id, CustomFieldModel.not_deleted_filter())
        )
        return result.scalar_one_or_none()

    async def max_position(self, entity_type: str) -> int:
        value = await self.session.scalar(
            select(func.max(CustomFieldModel.position)).where(
                CustomFieldModel.entity_type == entity_type, CustomFieldModel.not_deleted_filter()
            )
        )
        return -1 if value is None else int(value)

    async def create_field(self, field: CustomFieldModel) -> CustomFieldModel:
        self.session.add(field)
        await self.session.commit()
        await self.session.refresh(field)
        return field

    async def update_field(self, field: CustomFieldModel) -> CustomFieldModel:
        await self.session.commit()
        await self.session.refresh(field)
        return field

    async def soft_delete_field(self, field: CustomFieldModel) -> None:
        field.soft_delete(self.session)
        await self.session.commit()

    # ── значения ─────────────────────────────────────────────────────────────
    async def get_value(self, field_id: int, entity_id: int) -> CustomFieldValueModel | None:
        result = await self.session.execute(
            select(CustomFieldValueModel).where(
                CustomFieldValueModel.field_id == field_id, CustomFieldValueModel.entity_id == entity_id
            )
        )
        return result.scalar_one_or_none()

    async def list_values(
        self, entity_type: str, entity_id: int
    ) -> list[tuple[CustomFieldModel, CustomFieldValueModel]]:
        """Значения записи по живым полям её сущности (в порядке полей)."""
        result = await self.session.execute(
            select(CustomFieldModel, CustomFieldValueModel)
            .join(CustomFieldValueModel, CustomFieldValueModel.field_id == CustomFieldModel.id)
            .where(
                CustomFieldModel.entity_type == entity_type,
                CustomFieldModel.not_deleted_filter(),
                CustomFieldValueModel.entity_id == entity_id,
            )
            .order_by(CustomFieldModel.position, CustomFieldModel.id)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def save_value(self, value: CustomFieldValueModel) -> CustomFieldValueModel:
        self.session.add(value)
        await self.session.commit()
        await self.session.refresh(value)
        return value
