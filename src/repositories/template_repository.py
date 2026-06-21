from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from src.models.template import TaskTemplateModel, TaskTemplateItemModel
from src.models.task import SpisokModel, TaskStatus
from src.schemas.template import TemplateCreate, TemplateUpdate


class TemplateRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, owner_id: int, data: TemplateCreate) -> TaskTemplateModel:
        template = TaskTemplateModel(
            title=data.title,
            description=data.description,
            owner_id=owner_id,
        )
        self.session.add(template)
        await self.session.flush()

        for i, item_data in enumerate(data.items):
            item = TaskTemplateItemModel(
                template_id=template.id,
                title=item_data.title,
                priority=item_data.priority,
                order_index=item_data.order_index if item_data.order_index else i,
            )
            self.session.add(item)

        await self.session.flush()
        await self.session.refresh(template)
        return template

    async def get_all(self, owner_id: int) -> list[TaskTemplateModel]:
        result = await self.session.execute(
            select(TaskTemplateModel).where(TaskTemplateModel.owner_id == owner_id)
        )
        return list(result.unique().scalars().all())

    async def get_by_id(
        self, template_id: int, owner_id: int
    ) -> TaskTemplateModel | None:
        result = await self.session.execute(
            select(TaskTemplateModel).where(
                TaskTemplateModel.id == template_id,
                TaskTemplateModel.owner_id == owner_id,
            )
        )
        return result.unique().scalar_one_or_none()

    async def update(
        self, template: TaskTemplateModel, data: TemplateUpdate
    ) -> TaskTemplateModel:
        if data.title is not None:
            template.title = data.title
        if data.description is not None:
            template.description = data.description

        if data.items is not None:
            await self.session.execute(
                delete(TaskTemplateItemModel).where(
                    TaskTemplateItemModel.template_id == template.id
                )
            )
            for i, item_data in enumerate(data.items):
                item = TaskTemplateItemModel(
                    template_id=template.id,
                    title=item_data.title,
                    priority=item_data.priority,
                    order_index=item_data.order_index if item_data.order_index else i,
                )
                self.session.add(item)

        await self.session.flush()
        await self.session.refresh(template)
        return template

    async def delete(self, template: TaskTemplateModel) -> None:
        await self.session.delete(template)
        await self.session.flush()

    async def apply(
        self, template: TaskTemplateModel, project_id: int, user_id: int
    ) -> list[SpisokModel]:
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
