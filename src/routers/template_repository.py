from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.group import user_group
from src.models.task import SpisokModel, TaskStatus
from src.models.template import TaskTemplateItemModel, TaskTemplateModel
from src.schemas.template import TemplateCreate, TemplateUpdate


class TemplateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, owner_id: int, data: TemplateCreate) -> TaskTemplateModel:
        template = TaskTemplateModel(
            title=data.title,
            description=data.description,
            owner_id=owner_id,
            visibility=data.visibility,
            group_id=data.group_id,
        )
        self.session.add(template)
        await self.session.flush()

        for i, item_data in enumerate(data.items):
            item = TaskTemplateItemModel(
                template_id=template.id,
                title=item_data.title,
                priority=item_data.priority,
                # ВАЖНО: сравнение с `is not None`, а не просто truthy-проверка.
                # Раньше было `if item_data.order_index else i` — из-за этого
                # order_index=0 (валидная позиция "первый пункт") считался falsy
                # и молча подменялся на индекс перечисления `i`. Ломало
                # drag-and-drop переупорядочивание в TemplatesTab, если
                # перетащенный пункт получал order_index=0, но не был первым
                # в переданном списке.
                order_index=item_data.order_index if item_data.order_index is not None else i,
            )
            self.session.add(item)

        await self.session.flush()
        await self.session.refresh(template)
        return template

    async def get_all(
        self,
        owner_id: int,
        visibility_filter: str | None = None,
    ) -> list[TaskTemplateModel]:
        """
        Возвращает шаблоны доступные пользователю:
        - private: только свои
        - group: шаблоны групп в которых состоит пользователь
        - global: все глобальные

        visibility_filter — опциональный фильтр: "private" | "group" | "global" | None (все доступные)
        """
        # Подзапрос: группы пользователя
        user_groups_sq = select(user_group.c.group_id).where(user_group.c.user_id == owner_id).scalar_subquery()

        # Базовое условие доступности
        access_condition = or_(
            # Свои приватные
            and_(
                TaskTemplateModel.owner_id == owner_id,
                TaskTemplateModel.visibility == "private",
            ),
            # Групповые — только если состоит в группе
            and_(
                TaskTemplateModel.visibility == "group",
                TaskTemplateModel.group_id.in_(user_groups_sq),
            ),
            # Глобальные — все
            TaskTemplateModel.visibility == "global",
        )

        stmt = select(TaskTemplateModel).where(access_condition)

        # Доп. фильтр по типу видимости
        if visibility_filter == "private":
            stmt = stmt.where(
                TaskTemplateModel.owner_id == owner_id,
                TaskTemplateModel.visibility == "private",
            )
        elif visibility_filter == "group":
            stmt = stmt.where(
                TaskTemplateModel.visibility == "group",
                TaskTemplateModel.group_id.in_(user_groups_sq),
            )
        elif visibility_filter == "global":
            stmt = stmt.where(TaskTemplateModel.visibility == "global")

        result = await self.session.execute(stmt)
        return list(result.unique().scalars().all())

    async def get_by_id(self, template_id: int, user_id: int) -> TaskTemplateModel | None:
        """Получить шаблон если пользователь имеет к нему доступ."""
        user_groups_sq = select(user_group.c.group_id).where(user_group.c.user_id == user_id).scalar_subquery()

        access_condition = or_(
            and_(
                TaskTemplateModel.owner_id == user_id,
                TaskTemplateModel.visibility == "private",
            ),
            and_(
                TaskTemplateModel.visibility == "group",
                TaskTemplateModel.group_id.in_(user_groups_sq),
            ),
            TaskTemplateModel.visibility == "global",
        )

        result = await self.session.execute(
            select(TaskTemplateModel).where(
                TaskTemplateModel.id == template_id,
                access_condition,
            )
        )
        return result.unique().scalar_one_or_none()

    async def get_by_id_owner_only(self, template_id: int, owner_id: int) -> TaskTemplateModel | None:
        """Получить шаблон только если текущий пользователь — владелец (для edit/delete)."""
        result = await self.session.execute(
            select(TaskTemplateModel).where(
                TaskTemplateModel.id == template_id,
                TaskTemplateModel.owner_id == owner_id,
            )
        )
        return result.unique().scalar_one_or_none()

    async def update(self, template: TaskTemplateModel, data: TemplateUpdate) -> TaskTemplateModel:
        if data.title is not None:
            template.title = data.title
        if data.description is not None:
            template.description = data.description
        if data.visibility is not None:
            template.visibility = data.visibility
            template.group_id = data.group_id  # уже очищен валидатором если не group

        if data.items is not None:
            await self.session.execute(
                delete(TaskTemplateItemModel).where(TaskTemplateItemModel.template_id == template.id)
            )
            for i, item_data in enumerate(data.items):
                item = TaskTemplateItemModel(
                    template_id=template.id,
                    title=item_data.title,
                    priority=item_data.priority,
                    order_index=item_data.order_index if item_data.order_index is not None else i,
                )
                self.session.add(item)

        await self.session.flush()
        await self.session.refresh(template)
        return template

    async def delete(self, template: TaskTemplateModel) -> None:
        await self.session.delete(template)
        await self.session.flush()

    async def apply(self, template: TaskTemplateModel, project_id: int, user_id: int) -> list[SpisokModel]:
        created = []
        for item in sorted(template.items, key=lambda x: x.order_index):
            task = SpisokModel(
                title=item.title,
                priority=item.priority,
                status=TaskStatus.todo,
                project_id=project_id,
                author_id=user_id,
                user_id=user_id,
            )
            self.session.add(task)
            created.append(task)
        await self.session.flush()
        return created
