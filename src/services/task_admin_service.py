from src.db.unit_of_work import UnitOfWork
from src.db import get_session_maker
from src.models.audit import AuditLog
from src.core.metrics import tasks_deleted, tasks_restored, tasks_hard_deleted
import structlog

logger = structlog.get_logger()


class TaskAdminService:
    async def fetch_audit_entries(self, task_id: int) -> list:
        async with UnitOfWork(get_session_maker()) as uow:
            return await uow.audit.get_task_audit_entries(task_id)

    async def soft_delete(self, pk: int, admin_id: int | None) -> None:
        await logger.ainfo("task_soft_delete", task_id=pk, admin_id=admin_id)
        async with UnitOfWork(get_session_maker()) as uow:
            task = await uow.tasks.get_by_id(pk)
            if task and task.deleted_at is None:
                if admin_id:
                    uow.session.info["audit_user_id"] = admin_id
                task.soft_delete(uow.session)
                await uow.commit()
                tasks_deleted.inc()  # 👈

    async def bulk_soft_delete(self, pks: list[int], admin_id: int | None) -> None:
        await logger.ainfo("task_bulk_soft_delete", task_ids=pks, admin_id=admin_id)
        async with UnitOfWork(get_session_maker()) as uow:
            if admin_id:
                uow.session.info["audit_user_id"] = admin_id
            count = 0
            for pk in pks:
                task = await uow.tasks.get_by_id(pk)
                if task and task.deleted_at is None:
                    task.soft_delete(uow.session)
                    count += 1
            await uow.commit()
        tasks_deleted.inc(count)  # 👈 один раз после коммита

    async def bulk_restore(self, pks: list[int], admin_id: int | None) -> None:
        await logger.ainfo("task_restore", task_ids=pks, admin_id=admin_id)
        async with UnitOfWork(get_session_maker()) as uow:
            if admin_id:
                uow.session.info["audit_user_id"] = admin_id
            count = 0
            for pk in pks:
                task = await uow.tasks.get_by_id_include_deleted(pk)
                if task and task.deleted_at is not None:
                    task.restore(uow.session)
                    count += 1
            await uow.commit()
        tasks_restored.inc(count)  # 👈

    async def bulk_hard_delete(self, pks: list[int], admin_id: int | None) -> None:
        await logger.ainfo("task_hard_delete", task_ids=pks, admin_id=admin_id)
        async with UnitOfWork(get_session_maker()) as uow:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from src.models.task import SpisokModel

            count = 0
            for pk in pks:
                result = await uow.session.execute(
                    select(SpisokModel)
                    .where(SpisokModel.id == pk)
                    .options(selectinload(SpisokModel.comments))
                )
                obj = result.scalar_one_or_none()
                if obj:
                    audit = AuditLog(
                        user_id=admin_id,
                        entity_type=obj.__tablename__,
                        entity_id=obj.id,
                        action="delete",
                        old_values={
                            "hard_delete": True,
                            "deleted_at": (
                                obj.deleted_at.isoformat() if obj.deleted_at else None
                            ),
                        },
                        new_values=None,
                    )
                    uow.session.add(audit)
                    await uow.session.flush()
                    await uow.session.delete(obj)
                    count += 1
            await uow.commit()
        tasks_hard_deleted.inc(count)  # 👈


task_admin_service = TaskAdminService()
