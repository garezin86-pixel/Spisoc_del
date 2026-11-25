# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_deal_items.py
"""Оборудование сделки (Smart Tables, этап 2): строки «название + цена» внутри сделки.

Главные риски: правка закрытых продаж задним числом, правка чужой сделки, утечка между компаниями,
потеря истории при удалении. Сценарии идут через HTTP (две компании A и B, см. fixture world).
"""

import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from src.models.audit import AuditLog
from src.models.deal import DealModel
from src.services import deal_item_service
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


async def _stage_ids(client, headers) -> dict[str, int]:
    resp = await client.get("/api/pipeline", headers=headers)
    assert resp.status_code == 200, resp.text
    return {s["name"]: s["id"] for s in resp.json()["stages"]}


async def _add_deal(world_, stage_id: int, ws: str, owner: str | None, **fields) -> int:
    maker, ids, _ = world_
    async with maker() as s:
        deal = DealModel(
            workspace_id=ids[ws],
            client_id=ids["ca"] if ws == "a" else ids["cb"],
            stage_id=stage_id,
            owner_id=ids[owner] if owner else None,
            title=fields.pop("title", "Сделка"),
            **fields,
        )
        s.add(deal)
        await s.commit()
        return deal.id


async def _open_deal(client, world_, owner: str = "owner", **fields) -> tuple[int, dict]:
    _, _, logins = world_
    h = await _headers(client, logins, "a_manager")
    stages = await _stage_ids(client, h)
    return await _add_deal(world_, stages["Новая"], "a", owner, **fields), stages


def _items_url(deal_id: int, item_id: int | None = None) -> str:
    return f"/api/deals/{deal_id}/items" + (f"/{item_id}" if item_id is not None else "")


# ── создание, чтение, правка ─────────────────────────────────────────────────
async def test_owner_adds_edits_and_lists_items(client, world):
    _, _, logins = world
    deal_id, _ = await _open_deal(client, world, currency="USD")
    h = await _headers(client, logins, "owner")  # обычный пользователь, ответственный за сделку

    first = await client.post(_items_url(deal_id), json={"name": "  Роутер X  ", "price": 120.5}, headers=h)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["name"] == "Роутер X" and body["price"] == 120.5 and body["position"] == 0
    assert body["currency"] == "USD"  # валюта берётся у сделки
    second = await client.post(_items_url(deal_id), json={"name": "ONU Y"}, headers=h)  # цена не обязательна
    assert second.json()["price"] is None and second.json()["position"] == 1

    patched = await client.patch(_items_url(deal_id, body["id"]), json={"price": 99}, headers=h)
    assert patched.status_code == 200 and patched.json()["price"] == 99.0 and patched.json()["name"] == "Роутер X"
    cleared = await client.patch(_items_url(deal_id, body["id"]), json={"price": None}, headers=h)
    assert cleared.json()["price"] is None  # null очищает цену
    renamed = await client.patch(_items_url(deal_id, body["id"]), json={"name": "Роутер Z"}, headers=h)
    assert renamed.json()["name"] == "Роутер Z"

    listed = await client.get(_items_url(deal_id), headers=h)
    assert [i["name"] for i in listed.json()] == ["Роутер Z", "ONU Y"]


async def test_validation(client, world):
    _, _, logins = world
    deal_id, _ = await _open_deal(client, world)
    h = await _headers(client, logins, "owner")
    post = lambda payload: client.post(_items_url(deal_id), json=payload, headers=h)  # noqa: E731

    assert (await post({"name": "   "})).status_code == 422  # пустое после обрезки пробелов
    assert (await post({"name": "x" * 201})).status_code == 422
    assert (await post({"name": "Роутер", "price": -1})).status_code == 422
    assert (await post({"name": "Роутер", "price": 1.234})).status_code == 422  # больше 2 знаков
    assert (await post({"name": "Роутер", "price": 10**12})).status_code == 422  # не влезает в Numeric(14, 2)
    assert (await post({})).status_code == 422
    ok = await post({"name": "Роутер", "price": 0})  # нулевая цена допустима (например, в подарок)
    assert ok.status_code == 201
    assert (await client.patch(_items_url(deal_id, ok.json()["id"]), json={"name": None}, headers=h)).status_code == 422
    assert (await client.patch(_items_url(deal_id, ok.json()["id"]), json={"name": " "}, headers=h)).status_code == 422


async def test_item_limit(client, world, monkeypatch):
    _, _, logins = world
    monkeypatch.setattr(deal_item_service, "MAX_ITEMS_PER_DEAL", 2)
    deal_id, _ = await _open_deal(client, world)
    h = await _headers(client, logins, "owner")
    for name in ("A", "B"):
        assert (await client.post(_items_url(deal_id), json={"name": name}, headers=h)).status_code == 201
    assert (await client.post(_items_url(deal_id), json={"name": "C"}, headers=h)).status_code == 409


# ── права ────────────────────────────────────────────────────────────────────
async def test_permissions_on_open_deal(client, world):
    _, _, logins = world
    deal_id, _ = await _open_deal(client, world, owner="owner")
    owner_h = await _headers(client, logins, "owner")
    item = (await client.post(_items_url(deal_id), json={"name": "Роутер"}, headers=owner_h)).json()

    other_h = await _headers(client, logins, "other")  # не ответственный, не manager
    assert (await client.get(_items_url(deal_id), headers=other_h)).status_code == 200  # читать можно
    assert (await client.post(_items_url(deal_id), json={"name": "X"}, headers=other_h)).status_code == 403
    assert (await client.patch(_items_url(deal_id, item["id"]), json={"name": "X"}, headers=other_h)).status_code == 403
    assert (await client.delete(_items_url(deal_id, item["id"]), headers=other_h)).status_code == 403

    for who in ("a_manager", "a_admin"):
        h = await _headers(client, logins, who)
        assert (await client.post(_items_url(deal_id), json={"name": f"от {who}"}, headers=h)).status_code == 201
    assert (await client.get(_items_url(deal_id))).status_code in (401, 403)


async def test_closed_deal_items_only_for_managers(client, world):
    _, _, logins = world
    h_manager = await _headers(client, logins, "a_manager")
    stages = await _stage_ids(client, h_manager)
    won = await _add_deal(
        world, stages["Успех"], "a", "owner", amount=Decimal("500"), closed_at=datetime.now(timezone.utc)
    )
    lost = await _add_deal(world, stages["Отказ"], "a", "owner", closed_at=datetime.now(timezone.utc))
    owner_h = await _headers(client, logins, "owner")  # даже ответственный не правит закрытые сделки

    for deal_id in (won, lost):
        assert (await client.post(_items_url(deal_id), json={"name": "Роутер"}, headers=owner_h)).status_code == 403
        created = await client.post(_items_url(deal_id), json={"name": "Роутер"}, headers=h_manager)
        assert created.status_code == 201, created.text
        item_id = created.json()["id"]
        assert (await client.patch(_items_url(deal_id, item_id), json={"price": 5}, headers=owner_h)).status_code == 403
        assert (await client.delete(_items_url(deal_id, item_id), headers=owner_h)).status_code == 403
        assert (
            await client.patch(_items_url(deal_id, item_id), json={"price": 5}, headers=h_manager)
        ).status_code == 200
        assert (await client.get(_items_url(deal_id), headers=owner_h)).status_code == 200  # читать можно


async def test_isolation_between_companies(client, world):
    _, _, logins = world
    deal_id, _ = await _open_deal(client, world)
    ha = await _headers(client, logins, "a_manager")
    item = (await client.post(_items_url(deal_id), json={"name": "Роутер"}, headers=ha)).json()

    hb = await _headers(client, logins, "b_admin")
    assert (await client.get(_items_url(deal_id), headers=hb)).status_code == 404
    assert (await client.post(_items_url(deal_id), json={"name": "X"}, headers=hb)).status_code == 404
    assert (await client.patch(_items_url(deal_id, item["id"]), json={"name": "X"}, headers=hb)).status_code == 404
    assert (await client.delete(_items_url(deal_id, item["id"]), headers=hb)).status_code == 404
    assert (await client.get(_items_url(deal_id), headers=ha)).json()[0]["name"] == "Роутер"  # у A всё цело


async def test_item_must_belong_to_deal_in_url(client, world):
    _, _, logins = world
    deal1, _ = await _open_deal(client, world)
    deal2, _ = await _open_deal(client, world, title="Другая")
    h = await _headers(client, logins, "a_manager")
    item = (await client.post(_items_url(deal1), json={"name": "Роутер"}, headers=h)).json()
    assert (await client.patch(_items_url(deal2, item["id"]), json={"name": "X"}, headers=h)).status_code == 404
    assert (await client.delete(_items_url(deal2, item["id"]), headers=h)).status_code == 404


# ── удаление и история ───────────────────────────────────────────────────────
async def test_soft_delete_and_audit(client, world):
    maker, _, logins = world
    deal_id, _ = await _open_deal(client, world)
    h = await _headers(client, logins, "a_manager")
    item = (await client.post(_items_url(deal_id), json={"name": "Роутер", "price": 10}, headers=h)).json()
    await client.patch(_items_url(deal_id, item["id"]), json={"price": 20}, headers=h)

    assert (await client.delete(_items_url(deal_id, item["id"]), headers=h)).status_code == 200
    assert (await client.get(_items_url(deal_id), headers=h)).json() == []
    assert (await client.delete(_items_url(deal_id, item["id"]), headers=h)).status_code == 404  # повторно нельзя

    async with maker() as s:
        rows = (
            (await s.execute(select(AuditLog).where(AuditLog.entity_type == "deal_items").order_by(AuditLog.id)))
            .scalars()
            .all()
        )
    assert [r.action.value for r in rows] == ["create", "update", "delete"]
    assert {r.entity_id for r in rows} == {item["id"]}


async def test_deleted_deal_hides_items(client, world):
    maker, ids, logins = world
    deal_id, _ = await _open_deal(client, world)
    h = await _headers(client, logins, "a_manager")
    await client.post(_items_url(deal_id), json={"name": "Роутер"}, headers=h)
    async with maker() as s:
        deal = await s.get(DealModel, deal_id)
        deal.deleted_at = datetime.now(timezone.utc)
        await s.commit()
    assert (await client.get(_items_url(deal_id), headers=h)).status_code == 404
    assert (await client.post(_items_url(deal_id), json={"name": "X"}, headers=h)).status_code == 404


# ── подсказки названий ───────────────────────────────────────────────────────
async def test_suggest_names(client, world):
    _, _, logins = world
    deal_id, _ = await _open_deal(client, world)
    h = await _headers(client, logins, "a_manager")
    for name in ("Роутер X", "роутер x", "Роутер X", "ONU Y", "Кабель_5%"):
        await client.post(_items_url(deal_id), json={"name": name}, headers=h)

    allnames = (await client.get("/api/deal-items/suggest", headers=h)).json()
    assert allnames[0].lower() == "роутер x" and len(allnames) == 3  # регистр не плодит дубли, частые сверху
    assert (await client.get("/api/deal-items/suggest", params={"q": "onu"}, headers=h)).json() == ["ONU Y"]
    assert (await client.get("/api/deal-items/suggest", params={"q": "%"}, headers=h)).json() == ["Кабель_5%"]
    assert (await client.get("/api/deal-items/suggest", params={"q": "_"}, headers=h)).json() == ["Кабель_5%"]
    assert (await client.get("/api/deal-items/suggest", params={"q": "нет такого"}, headers=h)).json() == []

    hb = await _headers(client, logins, "b_admin")
    assert (await client.get("/api/deal-items/suggest", headers=hb)).json() == []  # чужие названия не видны


# ── таблица «Оборудование» (источник deal_items) ─────────────────────────────
async def test_table_source_equipment_report(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    stages = await _stage_ids(client, hm)
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    won_ivanov = await _add_deal(
        world, stages["Успех"], "a", "owner", amount=Decimal("900"), currency="UAH", closed_at=now, title="Продажа 1"
    )
    won_manager = await _add_deal(
        world, stages["Успех"], "a", "a_manager", amount=Decimal("50"), currency="USD", closed_at=now, title="Продажа 2"
    )
    open_deal = await _add_deal(world, stages["Новая"], "a", "owner", title="В работе")
    for deal_id, name, price in (
        (won_ivanov, "Роутер X", 120.5),
        (won_ivanov, "ONU Y", 80),
        (won_manager, "Кабель", None),
        (open_deal, "Не продано", 1),
    ):
        payload = {"name": name} | ({"price": price} if price is not None else {})
        assert (await client.post(_items_url(deal_id), json=payload, headers=hm)).status_code == 201

    won_filter = [{"field": "stage_kind", "op": "eq", "value": "won"}]
    resp = await client.get(
        "/api/tables/deal_items/rows",
        params={
            "columns": "owner_name,client_name,name,price,currency",
            "filters": json.dumps(won_filter),
            "sort": json.dumps([{"field": "id"}]),
        },
        headers=hm,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3  # «Не продано» из открытой сделки не попало
    assert [(r["owner_name"], r["client_name"], r["name"], r["price"], r["currency"]) for r in body["items"]] == [
        ("owner", "Ромашка", "Роутер X", 120.5, "UAH"),
        ("owner", "Ромашка", "ONU Y", 80.0, "UAH"),
        ("a_manager", "Ромашка", "Кабель", None, "USD"),
    ]

    only_manager = await client.get(
        "/api/tables/deal_items/rows",
        params={
            "columns": "name",
            "filters": json.dumps(won_filter + [{"field": "owner_id", "op": "eq", "value": ids["a_manager"]}]),
        },
        headers=hm,
    )
    assert [r["name"] for r in only_manager.json()["items"]] == ["Кабель"]

    # Удалённая позиция и позиции удалённой сделки в таблице не видны
    first = (await client.get(_items_url(won_ivanov), headers=hm)).json()[0]
    assert (await client.delete(_items_url(won_ivanov, first["id"]), headers=hm)).status_code == 200
    assert (await client.get("/api/tables/deal_items/rows", params={"columns": "name"}, headers=hm)).json()[
        "total"
    ] == 3
    maker = world[0]
    async with maker() as s:
        deal = await s.get(DealModel, won_manager)
        deal.deleted_at = datetime.now(timezone.utc)
        await s.commit()
    names = [
        r["name"]
        for r in (await client.get("/api/tables/deal_items/rows", params={"columns": "name"}, headers=hm)).json()[
            "items"
        ]
    ]
    assert set(names) == {"Не продано", "ONU Y"}  # «Кабель» ушёл вместе с удалённой сделкой

    hb = await _headers(client, logins, "b_admin")
    assert (await client.get("/api/tables/deal_items/rows", headers=hb)).json()["total"] == 0
