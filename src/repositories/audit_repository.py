from sqlalchemy import func, select
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

    async def get_global_feed(self, offset: int = 0, limit: int = 50) -> tuple[list[AuditLog], int]:
        """Глобальная лента активности ("Timeline") — по задачам и комментариям.

        Видимость задач в приложении не ограничена по владельцу (см.
        tasks_router.filter_tasks — без явного filter_user_group возвращает
        все задачи всем авторизованным пользователям), поэтому лента активности
        придерживается той же логики и не требует отдельного скоупинга.
        """
        base = select(AuditLog).where(AuditLog.entity_type.in_(("spisok_del", "comments")))

        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))

        result = await self.session.execute(
            base.options(selectinload(AuditLog.user)).order_by(AuditLog.changed_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total or 0
