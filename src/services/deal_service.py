# src/services/deal_service.py
from datetime import datetime, timezone

import structlog
from fastapi import HTTPException

from src.models.client import ClientModel
from src.models.deal import DealModel, PipelineModel, StageKind, StageModel
from src.models.user import UserModel, UserRole
from src.repositories.client_repository import ClientRepository
from src.repositories.deal_repository import DealRepository
from src.repositories.users_repository import UserRepository
from src.schemas.deal import DealCreate, DealMove, DealUpdate, StageCreate, StageUpdate

logger = structlog.get_logger()

DEFAULT_PIPELINE_NAME = "Продажи"
DEFAULT_STAGES: list[tuple[str, StageKind]] = [
    ("Новая", StageKind.open),
    ("Переговоры", StageKind.open),
    ("Предложение", StageKind.open),
    ("Выиграна", StageKind.won),
    ("Проиграна", StageKind.lost),
]

_PROCESS_FIELDS = ("amount", "owner_id", "expected_close_date")  # правят только admin и manager


def _is_manager(user: UserModel) -> bool:
    return user.role in (UserRole.admin, UserRole.manager)


class DealService:
    """Сделки и воронка.

    - Читать: все. Стадии воронки меняет только admin (создание, имя, порядок, удаление).
    - Создать сделку: admin, manager и ответственный за клиента. Другого ответственного назначает admin/manager.
    - Справочные поля (title, notes): ответственный по сделке, admin, manager.
    - Процессные (amount, owner_id, expected_close_date) и удаление: только admin и manager.
    - Перевод по стадиям (move): ответственный по сделке, admin, manager. Из закрытой стадии
      (won/lost) вернуть сделку может только admin или manager.
    - lost требует причину, won — сумму; closed_at ставится при закрытии.
    Чужая компания неотличима от несуществующего объекта: 404.
    """

    def __init__(self, deal_repo: DealRepository, client_repo: ClientRepository, user_repo: UserRepository):
        self.deal_repo = deal_repo
        self.client_repo = client_repo
        self.user_repo = user_repo

    # ── воронка ──────────────────────────────────────────────────────────────
    async def get_pipeline(self, current_user: UserModel) -> tuple[PipelineModel, list[StageModel]]:
        """Воронка компании; при первом обращении создаётся воронка по умолчанию."""
        pipeline = await self.deal_repo.get_default_pipeline()
        if pipeline is None:
            self.deal_repo.set_audit_user(current_user.id)
            pipeline = await self.deal_repo.create_pipeline_with_stages(DEFAULT_PIPELINE_NAME, DEFAULT_STAGES)
            await logger.ainfo("pipeline_created", pipeline_id=pipeline.id)
        return pipeline, await self.deal_repo.list_stages(pipeline.id)

    @staticmethod
    def _require_admin(user: UserModel) -> None:
        if user.role != UserRole.admin:
            raise HTTPException(403, "Менять воронку может только admin")

    async def _stage_or_404(self, stage_id: int) -> StageModel:
        stage = await self.deal_repo.get_stage(stage_id)
        if stage is None:
            raise HTTPException(404, "Стадия не найдена")
        return stage

    async def _move_stage_to(self, stage: StageModel, position: int) -> None:
        """Ставит стадию на позицию position (с нуля), сдвигая остальные; position у всех — 0..n-1 без дублей."""
        others = [s for s in await self.deal_repo.list_stages(stage.pipeline_id) if s.id != stage.id]
        others.insert(min(position, len(others)), stage)
        for index, item in enumerate(others):
            if item.position != index:
                item.position = index

    async def create_stage(self, data: StageCreate, current_user: UserModel) -> StageModel:
        self._require_admin(current_user)
        pipeline, _ = await self.get_pipeline(current_user)
        self.deal_repo.set_audit_user(current_user.id)
        position = await self.deal_repo.max_stage_position(pipeline.id) + 1
        stage = StageModel(pipeline_id=pipeline.id, name=data.name, position=position, kind=data.kind.value)
        stage = await self.deal_repo.create_stage(stage)
        if data.position is not None and data.position < position:
            await self._move_stage_to(stage, data.position)
            stage = await self.deal_repo.update_stage(stage)
        return stage

    async def update_stage(self, stage_id: int, data: StageUpdate, current_user: UserModel) -> StageModel:
        self._require_admin(current_user)
        stage = await self._stage_or_404(stage_id)
        self.deal_repo.set_audit_user(current_user.id)
        changes = data.model_dump(exclude_unset=True)
        if "name" in changes:
            stage.name = changes["name"]
        if "position" in changes:
            await self._move_stage_to(stage, changes["position"])
        return await self.deal_repo.update_stage(stage)

    async def delete_stage(self, stage_id: int, current_user: UserModel) -> dict:
        self._require_admin(current_user)
        stage = await self._stage_or_404(stage_id)
        if await self.deal_repo.count_deals_in_stage(stage_id) > 0:
            raise HTTPException(409, "В стадии есть сделки: сначала переведите их в другую стадию")
        if await self.deal_repo.count_stages_of_kind(stage.pipeline_id, stage.kind) <= 1:
            raise HTTPException(409, "Нельзя удалить последнюю стадию этого вида (open / won / lost)")
        self.deal_repo.set_audit_user(current_user.id)
        await self.deal_repo.soft_delete_stage(stage)
        return {"message": f"Stage {stage_id} deleted"}

    # ── сделки ───────────────────────────────────────────────────────────────
    async def _client_or_404(self, client_id: int) -> ClientModel:
        client = await self.client_repo.get_by_id(client_id)
        if client is None:
            raise HTTPException(404, "Клиент не найден")
        return client

    async def _deal_or_404(self, deal_id: int) -> DealModel:
        deal = await self.deal_repo.get_deal(deal_id)
        if deal is None:
            raise HTTPException(404, "Сделка не найдена")
        return deal

    async def _require_user_exists(self, user_id: int) -> None:
        if await self.user_repo.get_by_id(user_id) is None:
            raise HTTPException(404, "Пользователь не найден")

    @staticmethod
    def _is_deal_owner(deal: DealModel, user: UserModel) -> bool:
        return deal.owner_id == user.id

    async def list_deals(
        self,
        offset: int,
        limit: int,
        client_id: int | None = None,
        stage_id: int | None = None,
        owner_id: int | None = None,
    ):
        if client_id is not None:
            await self._client_or_404(client_id)
        return await self.deal_repo.list_deals(offset, limit, client_id, stage_id, owner_id)

    async def get_deal(self, deal_id: int) -> DealModel:
        return await self._deal_or_404(deal_id)

    async def create_deal(self, client_id: int, data: DealCreate, current_user: UserModel) -> DealModel:
        client = await self._client_or_404(client_id)
        if not (_is_manager(current_user) or client.owner_id == current_user.id):
            raise HTTPException(403, "Создавать сделки могут admin, manager и ответственный за клиента")

        pipeline, stages = await self.get_pipeline(current_user)
        if data.stage_id is not None:
            stage = await self._stage_or_404(data.stage_id)
            if stage.kind != StageKind.open.value:
                raise HTTPException(422, "Сделку можно создать только в открытой стадии")
        else:
            open_stages = [s for s in stages if s.kind == StageKind.open.value]
            if not open_stages:
                raise HTTPException(409, "В воронке нет открытых стадий")
            stage = open_stages[0]

        owner_id = current_user.id
        if data.owner_id is not None and data.owner_id != current_user.id:
            if not _is_manager(current_user):
                raise HTTPException(403, "Назначать ответственного может только admin или manager")
            await self._require_user_exists(data.owner_id)
            owner_id = data.owner_id

        self.deal_repo.set_audit_user(current_user.id)
        deal = DealModel(
            client_id=client_id,
            stage_id=stage.id,
            title=data.title,
            amount=data.amount,
            owner_id=owner_id,
            expected_close_date=data.expected_close_date,
            notes=data.notes,
        )
        created = await self.deal_repo.create_deal(deal)
        await logger.ainfo("deal_created", deal_id=created.id, client_id=client_id)
        return created

    async def update_deal(self, deal_id: int, data: DealUpdate, current_user: UserModel) -> DealModel:
        deal = await self._deal_or_404(deal_id)
        if not (_is_manager(current_user) or self._is_deal_owner(deal, current_user)):
            raise HTTPException(403, "Править сделку может ответственный, admin или manager")

        changes = data.model_dump(exclude_unset=True)
        if not _is_manager(current_user):
            changed = [f for f in _PROCESS_FIELDS if f in changes and getattr(deal, f) != changes[f]]
            if changed:
                raise HTTPException(403, "Менять сумму, ответственного и срок могут только admin и manager")
        if changes.get("owner_id") is not None:
            await self._require_user_exists(changes["owner_id"])
        if "amount" in changes and changes["amount"] is None:
            stage = await self._stage_or_404(deal.stage_id)
            if stage.kind == StageKind.won.value:
                raise HTTPException(422, "У выигранной сделки сумма обязательна")

        self.deal_repo.set_audit_user(current_user.id)
        for field, value in changes.items():
            setattr(deal, field, value)
        updated = await self.deal_repo.update_deal(deal)
        await logger.ainfo("deal_updated", deal_id=deal_id)
        return updated

    async def move_deal(self, deal_id: int, data: DealMove, current_user: UserModel) -> DealModel:
        deal = await self._deal_or_404(deal_id)
        if not (_is_manager(current_user) or self._is_deal_owner(deal, current_user)):
            raise HTTPException(403, "Переводить сделку может ответственный, admin или manager")

        target = await self._stage_or_404(data.stage_id)
        if target.id == deal.stage_id:
            return deal
        current = await self._stage_or_404(deal.stage_id)
        if current.kind != StageKind.open.value and not _is_manager(current_user):
            raise HTTPException(403, "Вернуть или перевести закрытую сделку может только admin или manager")

        now = datetime.now(timezone.utc)
        if target.kind == StageKind.lost.value:
            if not data.lost_reason:
                raise HTTPException(422, "Для проигранной сделки нужна причина (lost_reason)")
            lost_reason, closed_at = data.lost_reason, now
        elif target.kind == StageKind.won.value:
            if deal.amount is None:
                raise HTTPException(422, "Для выигранной сделки нужна сумма")
            lost_reason, closed_at = None, now
        else:
            lost_reason, closed_at = None, None

        self.deal_repo.set_audit_user(current_user.id)
        deal.stage_id = target.id
        deal.lost_reason = lost_reason
        deal.closed_at = closed_at
        moved = await self.deal_repo.update_deal(deal)
        await logger.ainfo("deal_moved", deal_id=deal_id, stage_id=target.id)
        return moved

    async def delete_deal(self, deal_id: int, current_user: UserModel) -> dict:
        deal = await self._deal_or_404(deal_id)
        if not _is_manager(current_user):
            raise HTTPException(403, "Удалять сделки могут только admin и manager")
        self.deal_repo.set_audit_user(current_user.id)
        await self.deal_repo.soft_delete_deal(deal)
        await logger.ainfo("deal_deleted", deal_id=deal_id)
        return {"message": f"Deal {deal_id} deleted"}
