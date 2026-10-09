# src/repositories/deal_repository.py
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.audit import AuditAction, AuditLog
from src.models.deal import DealModel, PipelineModel, StageKind, StageModel


class DealRepository:
    """Воронка, стадии и сделки. Изоляция по компании — слушатель tenant_scope; здесь — мягкое удаление."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def set_audit_user(self, user_id: int | None) -> None:
        self.session.info["audit_user_id"] = user_id

    # ── воронка ──────────────────────────────────────────────────────────────
    async def get_default_pipeline(self) -> PipelineModel | None:
        result = await self.session.execute(
            select(PipelineModel).where(PipelineModel.not_deleted_filter()).order_by(PipelineModel.id).limit(1)
        )
        return result.scalar_one_or_none()

    async def create_pipeline_with_stages(self, name: str, stages: list[tuple[str, StageKind]]) -> PipelineModel:
        pipeline = PipelineModel(name=name)
        self.session.add(pipeline)
        await self.session.flush()
        for position, (stage_name, kind) in enumerate(stages):
            self.session.add(StageModel(pipeline_id=pipeline.id, name=stage_name, position=position, kind=kind.value))
        await self.session.commit()
        await self.session.refresh(pipeline)
        return pipeline

    async def list_stages(self, pipeline_id: int) -> list[StageModel]:
        result = await self.session.execute(
            select(StageModel)
            .where(StageModel.pipeline_id == pipeline_id, StageModel.not_deleted_filter())
            .order_by(StageModel.position, StageModel.id)
        )
        return list(result.scalars().all())

    async def get_stage(self, stage_id: int) -> StageModel | None:
        result = await self.session.execute(
            select(StageModel).where(StageModel.id == stage_id, StageModel.not_deleted_filter())
        )
        return result.scalar_one_or_none()

    async def max_stage_position(self, pipeline_id: int) -> int:
        value = await self.session.scalar(
            select(func.max(StageModel.position)).where(
                StageModel.pipeline_id == pipeline_id, StageModel.not_deleted_filter()
            )
        )
        return -1 if value is None else value

    async def count_stages_of_kind(self, pipeline_id: int, kind: str) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(StageModel)
                .where(
                    StageModel.pipeline_id == pipeline_id,
                    StageModel.kind == kind,
                    StageModel.not_deleted_filter(),
                )
            )
            or 0
        )

    async def create_stage(self, stage: StageModel) -> StageModel:
        self.session.add(stage)
        await self.session.commit()
        await self.session.refresh(stage)
        return stage

    async def update_stage(self, stage: StageModel) -> StageModel:
        await self.session.commit()
        await self.session.refresh(stage)
        return stage

    async def soft_delete_stage(self, stage: StageModel) -> None:
        stage.soft_delete(self.session)
        await self.session.commit()

    async def get_stage_names(self, stage_ids: set[int]) -> dict[int, str]:
        """Названия стадий по id (включая удалённые — для истории)."""
        if not stage_ids:
            return {}
        result = await self.session.execute(select(StageModel.id, StageModel.name).where(StageModel.id.in_(stage_ids)))
        return {row[0]: row[1] for row in result.all()}

    async def count_deals_in_stage(self, stage_id: int) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(DealModel)
                .where(DealModel.stage_id == stage_id, DealModel.not_deleted_filter())
            )
            or 0
        )

    # ── сделки ───────────────────────────────────────────────────────────────
    async def get_deal(self, deal_id: int) -> DealModel | None:
        result = await self.session.execute(
            select(DealModel).where(DealModel.id == deal_id, DealModel.not_deleted_filter())
        )
        return result.scalar_one_or_none()

    async def list_stage_deals(self, stage_id: int) -> list[DealModel]:
        """Живые сделки колонки в порядке карточек."""
        result = await self.session.execute(
            select(DealModel)
            .where(DealModel.stage_id == stage_id, DealModel.not_deleted_filter())
            .order_by(DealModel.position, DealModel.id)
        )
        return list(result.scalars().all())

    async def list_deal_updates(self, deal_id: int) -> list[AuditLog]:
        result = await self.session.execute(
            select(AuditLog)
            .where(
                AuditLog.entity_type == "deals", AuditLog.entity_id == deal_id, AuditLog.action == AuditAction.update
            )
            .options(selectinload(AuditLog.user))
            .order_by(AuditLog.changed_at, AuditLog.id)
        )
        return list(result.scalars().all())

    async def list_deals(
        self,
        offset: int,
        limit: int,
        client_id: int | None = None,
        stage_id: int | None = None,
        owner_id: int | None = None,
    ) -> tuple[list[DealModel], int]:
        query = select(DealModel).where(DealModel.not_deleted_filter())
        if client_id is not None:
            query = query.where(DealModel.client_id == client_id)
        if stage_id is not None:
            query = query.where(DealModel.stage_id == stage_id)
        if owner_id is not None:
            query = query.where(DealModel.owner_id == owner_id)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        # В колонке канбана — порядок карточек; иначе новые сверху.
        order = (DealModel.position, DealModel.id) if stage_id is not None else (DealModel.id.desc(),)
        result = await self.session.execute(query.order_by(*order).offset(offset).limit(limit))
        return list(result.scalars().all()), total or 0

    async def create_deal(self, deal: DealModel) -> DealModel:
        self.session.add(deal)
        await self.session.commit()
        await self.session.refresh(deal)
        return deal

    async def update_deal(self, deal: DealModel) -> DealModel:
        await self.session.commit()
        await self.session.refresh(deal)
        return deal

    async def soft_delete_deal(self, deal: DealModel) -> None:
        deal.soft_delete(self.session)
        await self.session.commit()
