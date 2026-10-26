# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
"""Демо-данные: загрузка, удаление, права, изоляция компаний и сохранность настоящих данных."""

from datetime import datetime, timezone

from sqlalchemy import func, select

from src.models.client import ClientModel, ContactModel
from src.models.deal import DealModel, PipelineModel
from src.models.interaction import InteractionModel
from src.models.scheduled_event import ScheduledEventModel
from src.models.task import SpisokModel
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)

EXPECTED = {"clients": 12, "contacts": 5, "deals": 8, "interactions": 10, "tasks": 6, "events": 3}


async def _alive(maker, model, ws_id: int) -> int:
    async with maker() as s:
        return await s.scalar(
            select(func.count()).select_from(model).where(model.workspace_id == ws_id, model.deleted_at.is_(None))
        )


async def test_admin_loads_demo_data_with_everything_linked(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    resp = await client.post("/api/demo/load", headers=h)
    assert resp.status_code == 201, resp.text
    assert resp.json() == EXPECTED
    assert (await client.get("/api/demo", headers=h)).json() == {"loaded": True, "clients": 12}

    listing = (await client.get("/api/clients", params={"size": 100}, headers=h)).json()
    items = listing["items"]
    assert len(items) == 13  # 12 демо + настоящая «Ромашка»
    demo = [c for c in items if c["is_demo"]]
    assert len(demo) == 12 and {c["owner_id"] for c in demo} == {ids["a_admin"]}
    assert [c["name"] for c in items if not c["is_demo"]] == ["Ромашка"]
    assert {c["client_type"] for c in demo} == {"company", "person"}
    assert sum(c["client_type"] == "person" for c in demo) == 5

    due = (await client.get("/api/clients", params={"contact_due": "true", "size": 100}, headers=h)).json()["items"]
    assert len([c for c in due if c["is_demo"]]) == 4, "«Пора связаться» должно быть что показывать"

    for model, expected in (
        (ContactModel, 5),
        (DealModel, 8),
        (InteractionModel, 10),
        (SpisokModel, 6),
        (ScheduledEventModel, 3),
    ):
        assert await _alive(maker, model, ids["a"]) == expected, model.__name__


async def test_demo_deals_cover_open_won_and_lost_stages(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")
    await client.post("/api/demo/load", headers=h)
    csv_text = (await client.get("/api/deals/export", headers=h)).content.decode("utf-8-sig")
    rows = [line.split(";") for line in csv_text.strip().splitlines()[1:]]
    statuses = [r[4] for r in rows]
    assert len(rows) == 8 and statuses.count("Выиграна") == 1 and statuses.count("Проиграна") == 1
    assert statuses.count("В работе") == 6
    lost = next(r for r in rows if r[4] == "Проиграна")
    assert "Выбрали другого поставщика" in lost[10]


async def test_demo_tasks_have_overdue_and_done_and_belong_to_demo_clients(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    await client.post("/api/demo/load", headers=h)
    async with maker() as s:
        tasks = (await s.execute(select(SpisokModel).where(SpisokModel.workspace_id == ids["a"]))).scalars().all()
        demo_ids = set((await s.execute(select(ClientModel.id).where(ClientModel.is_demo.is_(True)))).scalars().all())
    assert len(tasks) == 6 and all(t.client_id in demo_ids for t in tasks)
    assert all(t.user_id == ids["a_admin"] and t.author_id == ids["a_admin"] for t in tasks)
    now = datetime.now(timezone.utc)

    def at(task):  # тестовая SQLite отдаёт даты без пояса (в Postgres они с поясом) — считаем их UTC
        return task.deadline if task.deadline.tzinfo else task.deadline.replace(tzinfo=timezone.utc)

    open_tasks = [t for t in tasks if t.status.value != "done"]
    assert any(at(t) < now for t in open_tasks), "нужна просроченная задача — на ней видно, как работают напоминания"
    assert any(at(t) > now for t in open_tasks)
    assert sum(t.status.value == "done" for t in tasks) == 1


async def test_loading_twice_is_rejected(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    assert (await client.post("/api/demo/load", headers=h)).status_code == 201
    again = await client.post("/api/demo/load", headers=h)
    assert again.status_code == 409 and "уже загружены" in again.json()["detail"]
    assert await _alive(maker, ClientModel, ids["a"]) == 13


async def test_only_admin_loads_and_removes_but_anyone_sees_status(client, world):
    _, _, logins = world
    for who in ("a_manager", "owner"):
        h = await _headers(client, logins, who)
        assert (await client.post("/api/demo/load", headers=h)).status_code == 403
        assert (await client.delete("/api/demo", headers=h)).status_code == 403
        assert (await client.get("/api/demo", headers=h)).json() == {"loaded": False, "clients": 0}


async def test_remove_deletes_only_demo_and_keeps_real_data(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    # настоящие данные: сделка и задача у «Ромашки»
    real_deal = await client.post(f"/api/clients/{ids['ca']}/deals", json={"title": "Настоящая сделка"}, headers=h)
    assert real_deal.status_code == 201, real_deal.text
    async with maker() as s:
        s.add(
            SpisokModel(
                title="Настоящая задача",
                author_id=ids["a_admin"],
                user_id=ids["a_admin"],
                client_id=ids["ca"],
                workspace_id=ids["a"],
            )
        )
        await s.commit()
    await client.post("/api/demo/load", headers=h)

    resp = await client.delete("/api/demo", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.json() == EXPECTED
    assert (await client.get("/api/demo", headers=h)).json() == {"loaded": False, "clients": 0}

    names = [c["name"] for c in (await client.get("/api/clients", params={"size": 100}, headers=h)).json()["items"]]
    assert names == ["Ромашка"]
    assert await _alive(maker, DealModel, ids["a"]) == 1
    assert await _alive(maker, SpisokModel, ids["a"]) == 1
    for model in (ContactModel, InteractionModel, ScheduledEventModel):
        assert await _alive(maker, model, ids["a"]) == 0, model.__name__


async def test_remove_without_demo_is_a_harmless_noop(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")
    resp = await client.delete("/api/demo", headers=h)
    assert resp.status_code == 200 and set(resp.json().values()) == {0}


async def test_demo_can_be_loaded_again_after_removal(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")
    await client.post("/api/demo/load", headers=h)
    await client.delete("/api/demo", headers=h)
    assert (await client.post("/api/demo/load", headers=h)).status_code == 201


async def test_demo_is_per_company(client, world):
    maker, ids, logins = world
    ha, hb = await _headers(client, logins, "a_admin"), await _headers(client, logins, "b_admin")
    assert (await client.post("/api/demo/load", headers=hb)).status_code == 201
    assert (await client.get("/api/demo", headers=ha)).json() == {"loaded": False, "clients": 0}
    assert (await client.post("/api/demo/load", headers=ha)).status_code == 201  # у A своё демо, не «уже загружено» у B
    await client.delete("/api/demo", headers=hb)
    assert (await client.get("/api/demo", headers=ha)).json() == {"loaded": True, "clients": 12}
    assert await _alive(maker, ClientModel, ids["b"]) == 1  # у B осталась только настоящая «Лютик»


async def test_demo_uses_existing_pipeline_instead_of_creating_another(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    await client.get("/api/pipelines", headers=h)  # создаёт воронку по умолчанию
    assert await _alive(maker, PipelineModel, ids["a"]) == 1
    await client.post("/api/demo/load", headers=h)
    assert await _alive(maker, PipelineModel, ids["a"]) == 1


async def test_demo_creates_default_pipeline_when_company_has_none(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    assert await _alive(maker, PipelineModel, ids["a"]) == 0
    await client.post("/api/demo/load", headers=h)
    assert await _alive(maker, PipelineModel, ids["a"]) == 1
