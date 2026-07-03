# src/repositories/attachment_repository.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.attachment_model import AttachmentModel


class AttachmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, attachment: AttachmentModel) -> AttachmentModel:
        self.session.add(attachment)
        await self.session.flush()  # получаем id без commit — UoW сделает commit сам
        await self.session.refresh(attachment)
        return attachment

    async def get_by_id(self, attachment_id: int) -> AttachmentModel | None:
        result = await self.session.execute(select(AttachmentModel).where(AttachmentModel.id == attachment_id))
        return result.scalar_one_or_none()

    async def get_by_task_id(self, task_id: int) -> list[AttachmentModel]:
        result = await self.session.execute(
            select(AttachmentModel).where(AttachmentModel.task_id == task_id).order_by(AttachmentModel.created_at.asc())
        )
        return list(result.scalars().all())

    async def delete(self, attachment: AttachmentModel) -> None:
        await self.session.delete(attachment)
