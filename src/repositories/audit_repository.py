from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.audit import AuditLog


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_task_audit_entries(self, task_id: int) -> list[AuditLog]:
        result = await self.session.execute(
            select(AuditLog)
            .options(selectinload(AuditLog.user))
            .where(
                AuditLog.entity_type == "spisok_del",
                AuditLog.entity_id == task_id,
            )
            .order_by(AuditLog.changed_at.desc())
            .limit(50)
        )
        return list(result.scalars().all())
