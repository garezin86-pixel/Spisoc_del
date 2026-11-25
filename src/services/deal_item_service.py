# src/services/deal_item_service.py
"""Оборудование сделки (Smart Tables, этап 2).

Права — как у самой сделки (DealService.update_deal): читать могут все; добавлять, править и удалять строки
может ответственный за сделку, admin и manager. Дополнительно: после закрытия сделки (стадия «Успех» или «Отказ»)
оборудование правят только admin и manager — чтобы закрытые продажи не менялись задним числом.
"""

import structlog
from fastapi import HTTPException

from src.models.deal import StageKind
from src.models.deal_item import DealItemModel
from src.models.user import UserModel, UserRole
from src.repositories.deal_item_repository import DealItemRepository
from src.repositories.deal_repository import DealRepository
from src.schemas.deal_item import DealItemCreate, DealItemUpdate

logger = structlog.get_logger()

MAX_ITEMS_PER_DEAL = 100
SUGGEST_LIMIT = 10
SUGGEST_SCAN_LIMIT = 1000  # сколько самых частых названий просматривать при подсказке


def _is_manager(user: UserModel) -> bool:
    return user.role in (UserRole.admin, UserRole.manager)


class DealItemService:
    def __init__(self, item_repo: DealItemRepository, deal_repo: DealRepository):
        self.item_repo = item_repo
        self.deal_repo = deal_repo

    async def _deal_or_404(self, deal_id: int):
        deal = await self.deal_repo.get_deal(deal_id)
        if deal is None:
            raise HTTPException(404, "Сделка не найдена")
        return deal

    async def _item_or_404(self, deal_id: int, item_id: int) -> DealItemModel:
        item = await self.item_repo.get(deal_id, item_id)
        if item is None:
            raise HTTPException(404, "Позиция не найдена")
        return item

    async def _require_can_edit(self, deal, user: UserModel) -> None:
        if not (_is_manager(user) or deal.owner_id == user.id):
            raise HTTPException(403, "Править оборудование сделки может ответственный, admin или manager")
        if not _is_manager(user):
            stage = await self.deal_repo.get_stage(deal.stage_id)
            if stage is not None and stage.kind != StageKind.open.value:
                raise HTTPException(403, "Оборудование закрытой сделки могут менять только admin и manager")

    async def list_items(self, deal_id: int) -> list[DealItemModel]:
        await self._deal_or_404(deal_id)
        return await self.item_repo.list_for_deal(deal_id)

    async def create_item(self, deal_id: int, data: DealItemCreate, current_user: UserModel) -> DealItemModel:
        deal = await self._deal_or_404(deal_id)
        await self._require_can_edit(deal, current_user)
        if await self.item_repo.count_for_deal(deal_id) >= MAX_ITEMS_PER_DEAL:
            raise HTTPException(409, f"В сделке не больше {MAX_ITEMS_PER_DEAL} позиций оборудования")
        self.item_repo.set_audit_user(current_user.id)
        item = DealItemModel(
            deal_id=deal_id,
            name=data.name,
            price=data.price,
            position=await self.item_repo.max_position(deal_id) + 1,
            author_id=current_user.id,
        )
        created = await self.item_repo.create(item)
        await logger.ainfo("deal_item_created", deal_id=deal_id, item_id=created.id)
        return created

    async def update_item(
        self, deal_id: int, item_id: int, data: DealItemUpdate, current_user: UserModel
    ) -> DealItemModel:
        deal = await self._deal_or_404(deal_id)
        await self._require_can_edit(deal, current_user)
        item = await self._item_or_404(deal_id, item_id)
        self.item_repo.set_audit_user(current_user.id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        updated = await self.item_repo.update(item)
        await logger.ainfo("deal_item_updated", deal_id=deal_id, item_id=item_id)
        return updated

    async def delete_item(self, deal_id: int, item_id: int, current_user: UserModel) -> dict:
        deal = await self._deal_or_404(deal_id)
        await self._require_can_edit(deal, current_user)
        item = await self._item_or_404(deal_id, item_id)
        self.item_repo.set_audit_user(current_user.id)
        await self.item_repo.soft_delete(item)
        await logger.ainfo("deal_item_deleted", deal_id=deal_id, item_id=item_id)
        return {"message": f"Deal item {item_id} deleted"}

    async def suggest_names(self, query: str) -> list[str]:
        """Подсказка названий: ранее введённые в компании, самые частые сверху.
        Написания, отличающиеся только регистром, считаются одним названием (показывается самое частое из них);
        `query` ищется как часть названия без учёта регистра."""
        needle = query.strip().casefold()
        merged: dict[str, tuple[int, int, str]] = {}  # casefold -> (всего, лучшее написание: сколько, само написание)
        for name, uses in await self.item_repo.name_usage(SUGGEST_SCAN_LIMIT):  # от частых к редким
            key = name.casefold()
            if needle and needle not in key:
                continue
            total, best_uses, best_name = merged.get(key, (0, 0, name))
            if uses > best_uses:
                best_uses, best_name = uses, name
            merged[key] = (total + uses, best_uses, best_name)
        ranked = sorted(merged.values(), key=lambda v: (-v[0], v[2].casefold()))
        return [v[2] for v in ranked[:SUGGEST_LIMIT]]
