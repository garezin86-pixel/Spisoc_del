# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_ai_permissions.py
"""Права AI-инструментов совпадают с правами обычного API.

Инструмент отказывает ДО вопроса «да/нет», но последнее слово — за сервисами. Если правила разойдутся, пользователь
получил бы вопрос «Создать сделку? да/нет» и отказ после «да» (или, хуже, обход прав). Тест прогоняет те же действия
через инструмент и через HTTP API от имени каждой роли и сравнивает «можно / нельзя».
"""

import pytest
from sqlalchemy import select

from src.ai import Confirm, Refuse, default_registry
from src.models.deal import DealModel
from tests.test_ai_tools import ai_ctx, call, make_deal
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)

ROLES = ["a_admin", "a_manager", "owner", "other"]  # owner — ответственный за клиента Ромашка; other — посторонний


def tool_allows(outcome) -> bool:
    return isinstance(outcome, Confirm)


@pytest.mark.parametrize("who", ROLES)
async def test_create_client_matches_api(client, world, who):
    maker, ids, logins = world
    api = await client.post("/api/clients", json={"name": "Новый"}, headers=await _headers(client, logins, who))
    async with ai_ctx(maker, ids, who) as ctx:
        offered = "create_client" in {t["function"]["name"] for t in default_registry().definitions(ctx.user)}
        outcome = await call(ctx, "create_client", name="Новый")
    assert offered == (api.status_code == 201) == tool_allows(outcome), (api.status_code, outcome)


@pytest.mark.parametrize("who", ROLES)
async def test_create_deal_matches_api(client, world, who):
    maker, ids, logins = world
    api = await client.post(
        f"/api/clients/{ids['ca']}/deals", json={"title": "Сделка"}, headers=await _headers(client, logins, who)
    )
    async with ai_ctx(maker, ids, who) as ctx:
        outcome = await call(ctx, "create_deal", client="Ромашка")
    assert (api.status_code == 201) == tool_allows(outcome), (api.status_code, outcome)
    if api.status_code == 403:
        assert isinstance(outcome, Refuse)


@pytest.mark.parametrize("who", ROLES)
async def test_add_note_matches_api(client, world, who):
    maker, ids, logins = world
    api = await client.post(
        f"/api/clients/{ids['ca']}/interactions",
        json={"type": "note", "summary": "Заметка"},
        headers=await _headers(client, logins, who),
    )
    async with ai_ctx(maker, ids, who) as ctx:
        outcome = await call(ctx, "add_note", client="Ромашка", text="Заметка")
    assert (api.status_code == 201) == tool_allows(outcome), (api.status_code, outcome)


@pytest.mark.parametrize("who", ROLES)
async def test_move_deal_matches_api(client, world, who):
    maker, ids, logins = world
    deal_id = await make_deal(maker, ids)  # создаёт owner: он ответственный по сделке
    async with maker() as s:
        stages = (await s.execute(select(DealModel.stage_id).where(DealModel.id == deal_id))).scalar_one()
    async with ai_ctx(maker, ids, who) as ctx:
        _, stage_list = await ctx.deals.get_pipeline(ctx.user, None)
        target = next(s for s in stage_list if s.name == "Переговоры")
        outcome = await call(ctx, "move_deal_stage", client="Ромашка", stage="Переговоры")
    assert stages != target.id
    api = await client.patch(
        f"/api/deals/{deal_id}/stage", json={"stage_id": target.id}, headers=await _headers(client, logins, who)
    )
    assert (api.status_code == 200) == tool_allows(outcome), (api.status_code, outcome)


async def test_reads_are_open_to_everyone_like_the_api(client, world):
    maker, ids, logins = world
    for who in ROLES:
        assert (await client.get("/api/clients", headers=await _headers(client, logins, who))).status_code == 200
        async with ai_ctx(maker, ids, who) as ctx:
            assert "Ромашка" in (await call(ctx, "find_client", query="Ромашка")).text
