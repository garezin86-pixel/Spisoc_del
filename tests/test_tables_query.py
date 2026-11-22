# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_tables_query.py
"""Smart Tables, этап 1: таблицы как живые запросы к данным CRM (только чтение).

Главные риски: утечка данных между компаниями, обход реестра колонок (произвольные поля/операции),
показ удалённых записей. Сценарии идут через HTTP с двумя компаниями A и B (см. fixture world).
"""

import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from src.models.client import ClientModel
from src.models.deal import DealModel
from src.models.interaction import InteractionModel
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


def _q(**params) -> dict:
    """Query-параметры: списки и словари — JSON-строкой."""
    return {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in params.items()}


async def _stage_ids(client, headers) -> dict[str, int]:
    resp = await client.get("/api/pipeline", headers=headers)
    assert resp.status_code == 200, resp.text
    return {s["name"]: s["id"] for s in resp.json()["stages"]}


async def _add_deal(world_, stage_id: int, client_id: int, ws: str, owner: str | None, **fields) -> int:
    maker, ids, _ = world_
    async with maker() as s:
        deal = DealModel(
            workspace_id=ids[ws],
            client_id=client_id,
            stage_id=stage_id,
            owner_id=ids[owner] if owner else None,
            **fields,
        )
        s.add(deal)
        await s.commit()
        return deal.id


# ── описание ─────────────────────────────────────────────────────────────────
async def test_sources_and_meta(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "other")  # читать может и обычный пользователь
    sources = (await client.get("/api/tables", headers=h)).json()
    assert {s["key"] for s in sources} == {"clients", "deals"}

    meta = (await client.get("/api/tables/deals/meta", headers=h)).json()
    cols = {c["key"]: c for c in meta["columns"]}
    assert cols["amount"]["manager_only"] is True and cols["amount"]["editable"] is True
    assert cols["client_name"]["linked"] is True and cols["client_name"]["editable"] is False
    assert cols["stage_kind"]["options"] == ["open", "won", "lost"]
    assert "contains" in cols["title"]["ops"] and "contains" not in cols["amount"]["ops"]
    assert set(meta["default_columns"]) <= set(cols)


async def test_unknown_source_is_404(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")
    assert (await client.get("/api/tables/secrets/meta", headers=h)).status_code == 404
    assert (await client.get("/api/tables/secrets/rows", headers=h)).status_code == 404


async def test_requires_auth(client, world):
    assert (await client.get("/api/tables/clients/rows")).status_code in (401, 403)


# ── клиенты ──────────────────────────────────────────────────────────────────
async def test_clients_rows_default_and_isolation(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_manager")
    body = (await client.get("/api/tables/clients/rows", headers=ha)).json()
    assert [r["name"] for r in body["items"]] == ["Ромашка"]  # «Лютик» из компании B не виден
    row = body["items"][0]
    assert row["_id"] == ids["ca"] and row["owner_name"] == "owner" and row["last_interaction_at"] is None
    assert row["_version"]  # токен версии для правки (этап 4)
    assert body["columns"] == ["name", "client_type", "status", "phone", "owner_name", "last_interaction_at"]

    hb = await _headers(client, logins, "b_admin")
    other = (await client.get("/api/tables/clients/rows", headers=hb)).json()
    assert [r["name"] for r in other["items"]] == ["Лютик"]


async def test_clients_filters_sort_and_paging(client, world):
    maker, ids, logins = world
    async with maker() as s:
        s.add_all(
            [
                ClientModel(name="Альфа", workspace_id=ids["a"], owner_id=ids["a_manager"], status="active"),
                ClientModel(name="Бета_100%", workspace_id=ids["a"], owner_id=None, status="inactive"),
                ClientModel(name="Гамма", workspace_id=ids["a"], owner_id=ids["owner"], status="active"),
            ]
        )
        await s.commit()
    h = await _headers(client, logins, "a_manager")

    async def rows(**params):
        resp = await client.get("/api/tables/clients/rows", params=_q(columns="name,status", **params), headers=h)
        assert resp.status_code == 200, resp.text
        return resp.json()

    assert [r["name"] for r in (await rows())["items"]] == ["Альфа", "Бета_100%", "Гамма", "Ромашка"]
    assert [r["name"] for r in (await rows(sort=[{"field": "name", "direction": "desc"}]))["items"]][0] == "Ромашка"

    active = await rows(filters=[{"field": "status", "op": "eq", "value": "active"}])
    assert [r["name"] for r in active["items"]] == ["Альфа", "Гамма", "Ромашка"]

    contains = await rows(filters=[{"field": "name", "op": "contains", "value": "т"}])
    assert [r["name"] for r in contains["items"]] == ["Бета_100%"]
    literal = await rows(filters=[{"field": "name", "op": "contains", "value": "%"}])  # % ищется буквально
    assert [r["name"] for r in literal["items"]] == ["Бета_100%"]

    no_owner = await rows(filters=[{"field": "owner_id", "op": "is_null"}])
    assert [r["name"] for r in no_owner["items"]] == ["Бета_100%"]
    two = await rows(filters=[{"field": "owner_id", "op": "in", "value": [ids["owner"], ids["a_manager"]]}])
    assert [r["name"] for r in two["items"]] == ["Альфа", "Гамма", "Ромашка"]

    page2 = await rows(page=2, size=3)
    assert page2["total"] == 4 and page2["pages"] == 2 and [r["name"] for r in page2["items"]] == ["Ромашка"]


async def test_clients_last_interaction_and_soft_delete(client, world):
    maker, ids, logins = world
    older = datetime(2026, 1, 5, tzinfo=timezone.utc)
    newer = datetime(2026, 3, 9, tzinfo=timezone.utc)
    async with maker() as s:
        gone = ClientModel(name="Удалённый", workspace_id=ids["a"], owner_id=ids["owner"])
        s.add_all(
            [
                gone,
                InteractionModel(client_id=ids["ca"], workspace_id=ids["a"], type="call", occurred_at=older),
                InteractionModel(client_id=ids["ca"], workspace_id=ids["a"], type="note", occurred_at=newer),
                InteractionModel(
                    client_id=ids["ca"],
                    workspace_id=ids["a"],
                    type="call",
                    occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                    deleted_at=datetime(2026, 6, 2, tzinfo=timezone.utc),  # удалённое не считается
                ),
            ]
        )
        await s.commit()
        gone.deleted_at = datetime.now(timezone.utc)
        await s.commit()
    h = await _headers(client, logins, "a_admin")
    resp = await client.get("/api/tables/clients/rows", params=_q(columns="name,last_interaction_at"), headers=h)
    items = resp.json()["items"]
    assert [r["name"] for r in items] == ["Ромашка"]  # удалённый клиент скрыт
    assert items[0]["last_interaction_at"].startswith("2026-03-09")

    recent = await client.get(
        "/api/tables/clients/rows",
        params=_q(columns="name", filters=[{"field": "last_interaction_at", "op": "gte", "value": "2026-02-01"}]),
        headers=h,
    )
    assert recent.json()["total"] == 1
    none = await client.get(
        "/api/tables/clients/rows",
        params=_q(columns="name", filters=[{"field": "last_interaction_at", "op": "gte", "value": "2026-04-01"}]),
        headers=h,
    )
    assert none.json()["total"] == 0


# ── сделки ───────────────────────────────────────────────────────────────────
async def test_deals_table_manager_client_stage(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    stages = await _stage_ids(client, h)
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    await _add_deal(world, stages["Новая"], ids["ca"], "a", "owner", title="Открытая")
    won1 = await _add_deal(
        world,
        stages["Успех"],
        ids["ca"],
        "a",
        "a_manager",
        title="Роутер",
        amount=Decimal("120.50"),
        currency="USD",
        closed_at=now,
    )
    await _add_deal(
        world,
        stages["Успех"],
        ids["ca"],
        "a",
        "owner",
        title="ONU",
        amount=Decimal("800"),
        currency="UAH",
        closed_at=now,
    )
    await _add_deal(world, stages["Отказ"], ids["ca"], "a", "owner", title="Отказ", lost_reason="дорого", closed_at=now)

    resp = await client.get(
        "/api/tables/deals/rows",
        params=_q(
            columns="title,client_name,owner_name,amount,currency,stage_kind",
            filters=[{"field": "stage_kind", "op": "eq", "value": "won"}],
            sort=[{"field": "amount", "direction": "desc"}],
        ),
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert [r["title"] for r in body["items"]] == ["ONU", "Роутер"]
    assert body["items"][0]["client_name"] == "Ромашка" and body["items"][0]["owner_name"] == "owner"
    assert body["items"][1]["amount"] == "120.50" and body["items"][1]["currency"] == "USD"  # деньги строкой
    assert body["items"][1]["_id"] == won1

    by_manager = await client.get(
        "/api/tables/deals/rows",
        params=_q(
            columns="title",
            filters=[
                {"field": "stage_kind", "op": "eq", "value": "won"},
                {"field": "owner_id", "op": "eq", "value": ids["a_manager"]},
                {"field": "amount", "op": "gte", "value": "100"},
            ],
        ),
        headers=h,
    )
    assert [r["title"] for r in by_manager.json()["items"]] == ["Роутер"]


async def test_deals_isolation_and_hidden_deleted(client, world):
    maker, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    stages = await _stage_ids(client, ha)
    live = await _add_deal(world, stages["Новая"], ids["ca"], "a", "owner", title="Живая")
    await _add_deal(
        world, stages["Новая"], ids["ca"], "a", "owner", title="Удалённая", deleted_at=datetime.now(timezone.utc)
    )
    client_gone = await _add_deal(world, stages["Новая"], ids["ca"], "a", "owner", title="Клиент удалён")

    hb = await _headers(client, logins, "b_admin")
    assert (await client.get("/api/tables/deals/rows", headers=hb)).json()["total"] == 0  # чужая компания

    async with maker() as s:
        c = await s.get(ClientModel, ids["ca"])
        c.deleted_at = datetime.now(timezone.utc)
        await s.commit()
    assert (await client.get("/api/tables/deals/rows", headers=ha)).json()[
        "total"
    ] == 0  # сделки удалённого клиента скрыты
    async with maker() as s:
        c = await s.get(ClientModel, ids["ca"])
        c.deleted_at = None
        await s.commit()
    titles = [r["title"] for r in (await client.get("/api/tables/deals/rows", headers=ha)).json()["items"]]
    assert titles == ["Клиент удалён", "Живая"]  # по умолчанию новые сверху; удалённая не показана
    assert live and client_gone


# ── защита от неверного ввода ────────────────────────────────────────────────
async def test_registry_blocks_bad_input(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")

    async def code(**params) -> int:
        return (await client.get("/api/tables/deals/rows", params=_q(**params), headers=h)).status_code

    assert await code(columns="title,password_hash") == 422  # колонки нет в реестре
    assert await code(filters=[{"field": "workspace_id", "op": "eq", "value": 2}]) == 422  # чужое поле
    assert await code(filters=[{"field": "amount", "op": "contains", "value": "1"}]) == 422  # операция не для типа
    assert await code(filters=[{"field": "amount", "op": "gt", "value": "abc"}]) == 422  # значение не того типа
    assert await code(filters=[{"field": "amount", "op": "gt", "value": True}]) == 422  # bool — не число
    assert await code(filters=[{"field": "stage_kind", "op": "eq", "value": "wat"}]) == 422  # нет в options
    assert await code(filters=[{"field": "closed_at", "op": "gte", "value": "вчера"}]) == 422
    assert await code(filters=[{"field": "owner_id", "op": "in", "value": []}]) == 422
    assert await code(filters=[{"field": "title", "op": "eq"}]) == 422  # нужно значение
    assert await code(filters=[{"field": "title", "op": "DROP TABLE", "value": "x"}]) == 422  # неизвестная операция
    assert await code(sort=[{"field": "nope", "direction": "asc"}]) == 422
    assert await code(sort=[{"field": "id"}] * 4) == 422  # не больше 3 ключей
    assert await code(filters="{не json") == 422
    assert await code(filters=[{"field": "title", "op": "eq", "value": "x"}] * 21) == 422
    assert await code(size=500) == 422
    assert await code(page=0) == 422
    assert await code() == 200
    assert await code(filters=[{"field": "title", "op": "is_null"}], sort=[{"field": "title"}]) == 200


async def test_state_unchanged_by_reads(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    await client.get("/api/tables/clients/rows", headers=h)
    async with maker() as s:
        names = (await s.execute(select(ClientModel.name).order_by(ClientModel.id))).scalars().all()
    assert names == ["Ромашка", "Лютик"]
