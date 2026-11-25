# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_custom_fields.py
"""Свои поля (Smart Tables, этап 3): поля клиентов и сделок, их значения и колонки в таблицах.

Главные риски: чужие поля и значения (две компании), обход прав на правку записи, значение не того типа,
потеря значений при удалении поля, неверные фильтры по своим колонкам.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from src.models.audit import AuditLog
from src.models.client import ClientModel
from src.services import custom_field_service
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)
from tests.test_deal_items import _add_deal, _items_url, _stage_ids


async def _field(client, h, name="ЛС", entity_type="client", field_type="text", **extra) -> dict:
    resp = await client.post(
        "/api/custom-fields",
        json={"entity_type": entity_type, "name": name, "field_type": field_type, **extra},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _put(client, h, field_id: int, entity_id: int, value):
    return client.put(f"/api/custom-fields/{field_id}/values/{entity_id}", json={"value": value}, headers=h)


# ── поля ─────────────────────────────────────────────────────────────────────
async def test_manager_creates_lists_and_plain_user_cannot_manage(client, world):
    _, _, logins = world
    hm = await _headers(client, logins, "a_manager")
    ls = await _field(client, hm, "  ЛС  ")
    assert ls["name"] == "ЛС" and ls["field_type"] == "text" and ls["options"] is None and ls["position"] == 0
    tariff = await _field(client, hm, "Тариф", field_type="select", options=["  Старт ", "Премиум"])
    assert tariff["options"] == ["Старт", "Премиум"] and tariff["position"] == 1
    await _field(client, hm, "Результат", entity_type="deal")

    ho = await _headers(client, logins, "other")  # обычный пользователь: читать можно
    names = [f["name"] for f in (await client.get("/api/custom-fields", headers=ho)).json()]
    assert names == ["ЛС", "Тариф", "Результат"]
    only_deal = (await client.get("/api/custom-fields", params={"entity_type": "deal"}, headers=ho)).json()
    assert [f["name"] for f in only_deal] == ["Результат"]

    body = {"entity_type": "client", "name": "Новое", "field_type": "text"}
    assert (await client.post("/api/custom-fields", json=body, headers=ho)).status_code == 403
    assert (await client.patch(f"/api/custom-fields/{ls['id']}", json={"name": "X"}, headers=ho)).status_code == 403
    assert (await client.delete(f"/api/custom-fields/{ls['id']}", headers=ho)).status_code == 403
    assert (await client.get("/api/custom-fields")).status_code in (401, 403)


async def test_field_validation(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")

    async def code(**payload) -> int:
        body = {"entity_type": "client", "name": "Поле", "field_type": "text"} | payload
        return (await client.post("/api/custom-fields", json=body, headers=h)).status_code

    assert await code(name="   ") == 422
    assert await code(name="x" * 101) == 422
    assert await code(entity_type="task") == 422
    assert await code(field_type="json") == 422
    assert await code(field_type="select") == 422  # у списка должны быть значения
    assert await code(field_type="select", options=[]) == 422
    assert await code(field_type="select", options=["A", "a"]) == 422  # повтор без учёта регистра
    assert await code(field_type="select", options=["A", " "]) == 422
    assert await code(field_type="select", options=["x" * 101]) == 422
    assert await code(field_type="select", options=[f"v{i}" for i in range(51)]) == 422
    assert await code(field_type="text", options=["A"]) == 422  # значения списка только у select
    assert await code(field_type="select", options=["A", "B"]) == 201


async def test_unique_name_and_limit(client, world, monkeypatch):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    await _field(client, h, "ЛС")
    dup = {"entity_type": "client", "name": "лс", "field_type": "number"}
    assert (await client.post("/api/custom-fields", json=dup, headers=h)).status_code == 409  # регистр не важен
    await _field(client, h, "ЛС", entity_type="deal")  # то же имя у другой сущности — можно

    monkeypatch.setattr(custom_field_service, "MAX_FIELDS_PER_ENTITY", 2)
    await _field(client, h, "Второе")
    over = {"entity_type": "client", "name": "Третье", "field_type": "text"}
    assert (await client.post("/api/custom-fields", json=over, headers=h)).status_code == 409
    await _field(client, h, "Другое", entity_type="deal")  # лимит считается по сущности


async def test_update_and_delete_field(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    a = await _field(client, h, "A")
    b = await _field(client, h, "Тариф", field_type="select", options=["1", "2"])

    patched = await client.patch(f"/api/custom-fields/{a['id']}", json={"name": "ЛС", "position": 5}, headers=h)
    assert patched.status_code == 200 and patched.json()["name"] == "ЛС" and patched.json()["position"] == 5
    assert (await client.patch(f"/api/custom-fields/{a['id']}", json={"name": "тариф"}, headers=h)).status_code == 409
    assert (await client.patch(f"/api/custom-fields/{a['id']}", json={"name": "ЛС"}, headers=h)).status_code == 200
    assert (await client.patch(f"/api/custom-fields/{a['id']}", json={"options": ["x"]}, headers=h)).status_code == 422
    assert (await client.patch(f"/api/custom-fields/{a['id']}", json={"name": None}, headers=h)).status_code == 422
    changed = await client.patch(f"/api/custom-fields/{b['id']}", json={"options": ["1", "2", "3"]}, headers=h)
    assert changed.json()["options"] == ["1", "2", "3"]
    retyped = await client.patch(f"/api/custom-fields/{a['id']}", json={"field_type": "number"}, headers=h)
    assert retyped.json()["field_type"] == "text"  # тип после создания не меняется

    assert (await client.delete(f"/api/custom-fields/{b['id']}", headers=h)).status_code == 200
    names = [f["name"] for f in (await client.get("/api/custom-fields", headers=h)).json()]
    assert names == ["ЛС"]
    assert (await client.delete(f"/api/custom-fields/{b['id']}", headers=h)).status_code == 404
    assert (await _put(client, h, b["id"], 1, "1")).status_code == 404  # в удалённое поле писать нельзя
    again = await _field(client, h, "Тариф", field_type="text")  # имя удалённого поля свободно
    assert again["id"] != b["id"]


async def test_isolation_between_companies(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_manager")
    field = await _field(client, ha, "ЛС")
    assert (await _put(client, ha, field["id"], ids["ca"], "123")).status_code == 200

    hb = await _headers(client, logins, "b_admin")
    assert (await client.get("/api/custom-fields", headers=hb)).json() == []
    assert (await client.patch(f"/api/custom-fields/{field['id']}", json={"name": "X"}, headers=hb)).status_code == 404
    assert (await client.delete(f"/api/custom-fields/{field['id']}", headers=hb)).status_code == 404
    assert (await _put(client, hb, field["id"], ids["cb"], "999")).status_code == 404
    own = await _field(client, hb, "ЛС")  # то же имя в другой компании — отдельное поле
    assert (await _put(client, hb, own["id"], ids["ca"], "x")).status_code == 404  # чужая запись не видна
    assert (await _put(client, hb, own["id"], ids["cb"], "999")).status_code == 200
    assert (
        await client.get(
            "/api/custom-fields/values", params={"entity_type": "client", "entity_id": ids["ca"]}, headers=hb
        )
    ).json() == []


# ── значения ─────────────────────────────────────────────────────────────────
async def test_set_value_permissions_and_listing(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    ls = await _field(client, hm, "ЛС")
    owner_h = await _headers(client, logins, "owner")  # ответственный за клиента ca
    other_h = await _headers(client, logins, "other")

    ok = await _put(client, owner_h, ls["id"], ids["ca"], "  123456 ")
    assert ok.status_code == 200 and ok.json() == {"field_id": ls["id"], "entity_id": ids["ca"], "value": "123456"}
    assert (await _put(client, other_h, ls["id"], ids["ca"], "1")).status_code == 403
    assert (await _put(client, hm, ls["id"], ids["ca"], "654321")).status_code == 200  # manager правит любые
    assert (await _put(client, hm, ls["id"], 99999, "1")).status_code == 404  # записи нет

    values = await client.get(
        "/api/custom-fields/values", params={"entity_type": "client", "entity_id": ids["ca"]}, headers=other_h
    )  # читать могут все
    assert values.json() == [{"field_id": ls["id"], "entity_id": ids["ca"], "value": "654321"}]

    assert (await _put(client, owner_h, ls["id"], ids["ca"], None)).json()["value"] is None  # null очищает
    empty = await client.get(
        "/api/custom-fields/values", params={"entity_type": "client", "entity_id": ids["ca"]}, headers=hm
    )
    assert empty.json() == []
    assert (await _put(client, hm, ls["id"], ids["ca"], "")).json()["value"] is None  # пустая строка тоже очищает
    maker = world[0]
    async with maker() as s:  # очистка пустого значения не плодит строк
        from src.models.custom_field import CustomFieldValueModel

        other_client = ClientModel(name="Пустой", workspace_id=ids["a"], owner_id=ids["owner"])
        s.add(other_client)
        await s.commit()
        before = len((await s.execute(select(CustomFieldValueModel))).scalars().all())
    assert (await _put(client, hm, ls["id"], other_client.id, None)).status_code == 200
    async with maker() as s:
        assert len((await s.execute(select(CustomFieldValueModel))).scalars().all()) == before


async def test_value_validation_by_type(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    number = await _field(client, h, "Баллы", field_type="number")
    day = await _field(client, h, "Визит", field_type="date")
    tariff = await _field(client, h, "Тариф", field_type="select", options=["Старт", "Премиум"])
    vip = await _field(client, h, "VIP", field_type="boolean")
    text = await _field(client, h, "Заметка")
    ca = ids["ca"]

    ok = await _put(client, h, number["id"], ca, "12.5")  # число можно строкой
    assert ok.json()["value"] == 12.5
    assert (await _put(client, h, number["id"], ca, 7)).json()["value"] == 7.0
    for bad in ("abc", True, 12.34567, 10**14, "NaN", "Infinity", [1]):
        assert (await _put(client, h, number["id"], ca, bad)).status_code == 422, bad

    assert (await _put(client, h, day["id"], ca, "2026-11-21")).json()["value"] == "2026-11-21"
    for bad in ("21.11.2026", "2026-13-40", "2026-11-21T10:00", 20261121):
        assert (await _put(client, h, day["id"], ca, bad)).status_code == 422, bad

    assert (await _put(client, h, tariff["id"], ca, "Премиум")).json()["value"] == "Премиум"
    assert (await _put(client, h, tariff["id"], ca, "премиум")).status_code == 422  # только значения из списка
    assert (await _put(client, h, tariff["id"], ca, 5)).status_code == 422

    assert (await _put(client, h, vip["id"], ca, True)).json()["value"] is True
    assert (await _put(client, h, vip["id"], ca, False)).json()["value"] is False  # false — это значение, не очистка
    for bad in ("true", 1, "да"):
        assert (await _put(client, h, vip["id"], ca, bad)).status_code == 422, bad

    assert (await _put(client, h, text["id"], ca, "x" * 2000)).status_code == 200
    assert (await _put(client, h, text["id"], ca, "x" * 2001)).status_code == 422
    assert (
        await _put(client, h, text["id"], ca, 123)
    ).status_code == 422  # число в текстовое поле — ошибка, не приведение

    filled = await client.get("/api/custom-fields/values", params={"entity_type": "client", "entity_id": ca}, headers=h)
    assert {v["field_id"]: v["value"] for v in filled.json()} == {
        number["id"]: 7.0,
        day["id"]: "2026-11-21",
        tariff["id"]: "Премиум",
        vip["id"]: False,
        text["id"]: "x" * 2000,
    }


async def test_deal_values_follow_deal_owner(client, world):
    _, _, logins = world
    hm = await _headers(client, logins, "a_manager")
    stages = await _stage_ids(client, hm)
    deal_id = await _add_deal(world, stages["Новая"], "a", "owner")
    result = await _field(client, hm, "Результат", entity_type="deal")
    assert (
        await _put(client, await _headers(client, logins, "owner"), result["id"], deal_id, "Согласился")
    ).status_code == 200
    assert (await _put(client, await _headers(client, logins, "other"), result["id"], deal_id, "X")).status_code == 403
    assert (await _put(client, hm, result["id"], 99999, "X")).status_code == 404
    shown = await client.get(
        "/api/custom-fields/values", params={"entity_type": "deal", "entity_id": deal_id}, headers=hm
    )
    assert [v["value"] for v in shown.json()] == ["Согласился"]


async def test_values_are_audited(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    ls = await _field(client, h, "ЛС")
    await _put(client, h, ls["id"], ids["ca"], "111")
    await _put(client, h, ls["id"], ids["ca"], "222")
    async with maker() as s:
        rows = (
            (
                await s.execute(
                    select(AuditLog).where(AuditLog.entity_type == "custom_field_values").order_by(AuditLog.id)
                )
            )
            .scalars()
            .all()
        )
        field_rows = (await s.execute(select(AuditLog).where(AuditLog.entity_type == "custom_fields"))).scalars().all()
    assert [r.action.value for r in rows] == ["create", "update"]
    assert rows[0].new_values["value_text"] == "111" and rows[1].old_values["value_text"] == "111"
    assert rows[1].new_values["value_text"] == "222"
    assert len(field_rows) == 1  # создание поля тоже в аудите


# ── колонки в таблицах ───────────────────────────────────────────────────────
async def test_clients_table_with_custom_columns(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    ls = await _field(client, h, "ЛС")
    points = await _field(client, h, "Баллы", field_type="number")
    visit = await _field(client, h, "Визит", field_type="date")
    tariff = await _field(client, h, "Тариф", field_type="select", options=["Старт", "Премиум"])
    vip = await _field(client, h, "VIP", field_type="boolean")
    async with maker() as s:
        extra = [ClientModel(name=n, workspace_id=ids["a"], owner_id=ids["owner"]) for n in ("Альфа", "Бета", "Гамма")]
        s.add_all(extra)
        await s.commit()
        alpha, beta, gamma = (c.id for c in extra)
    for client_id, values in (
        (alpha, [(ls, "LS-100"), (points, 10), (visit, "2026-03-01"), (tariff, "Старт"), (vip, True)]),
        (beta, [(ls, "LS-200"), (points, 30), (visit, "2026-06-01"), (tariff, "Премиум"), (vip, False)]),
        (gamma, [(ls, "XX-300")]),
    ):
        for field, value in values:
            assert (await _put(client, h, field["id"], client_id, value)).status_code == 200

    def key(field) -> str:
        return f"cf_{field['id']}"

    meta = (await client.get("/api/tables/clients/meta", headers=h)).json()
    cols = {c["key"]: c for c in meta["columns"]}
    assert cols[key(ls)]["label"] == "ЛС" and cols[key(ls)]["type"] == "text" and cols[key(ls)]["editable"] is True
    assert cols[key(ls)]["linked"] is False and "contains" in cols[key(ls)]["ops"]
    assert cols[key(tariff)]["options"] == ["Старт", "Премиум"] and cols[key(vip)]["ops"] == ["eq"]
    assert meta["default_columns"] == ["name", "client_type", "status", "phone", "owner_name", "last_interaction_at"]

    async def rows(**params):
        query = {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in params.items()}
        query.setdefault("columns", "name")
        resp = await client.get("/api/tables/clients/rows", params=query, headers=h)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def names(body) -> list[str]:
        return [r["name"] for r in body["items"]]

    cols_param = ",".join(["name", key(ls), key(points), key(visit), key(tariff), key(vip)])
    body = await rows(columns=cols_param, filters=[{"field": "name", "op": "eq", "value": "Альфа"}])
    assert body["items"][0] | {"_id": 0, "_version": ""} == {
        "_id": 0,
        "_version": "",
        "name": "Альфа",
        key(ls): "LS-100",
        key(points): 10.0,
        key(visit): "2026-03-01",
        key(tariff): "Старт",
        key(vip): True,
    }
    empty_row = (await rows(columns=cols_param, filters=[{"field": "name", "op": "eq", "value": "Ромашка"}]))["items"][
        0
    ]
    assert all(empty_row[key(f)] is None for f in (ls, points, visit, tariff, vip))  # значений нет — None

    assert names(await rows(filters=[{"field": key(ls), "op": "eq", "value": "LS-200"}])) == ["Бета"]
    assert names(await rows(filters=[{"field": key(ls), "op": "contains", "value": "ls-"}])) == ["Альфа", "Бета"]
    assert names(await rows(filters=[{"field": key(points), "op": "gte", "value": 20}])) == ["Бета"]
    assert names(await rows(filters=[{"field": key(visit), "op": "lt", "value": "2026-04-01"}])) == ["Альфа"]
    assert names(await rows(filters=[{"field": key(tariff), "op": "in", "value": ["Старт", "Премиум"]}])) == [
        "Альфа",
        "Бета",
    ]
    assert names(await rows(filters=[{"field": key(vip), "op": "eq", "value": False}])) == ["Бета"]
    assert names(await rows(filters=[{"field": key(points), "op": "is_null"}])) == ["Гамма", "Ромашка"]
    assert names(await rows(filters=[{"field": key(ls), "op": "not_null"}])) == ["Альфа", "Бета", "Гамма"]
    desc = await rows(sort=[{"field": key(points), "direction": "desc"}])
    assert names(desc)[:2] == ["Бета", "Альфа"]  # у остальных значения нет — они в конце
    assert names(await rows(sort=[{"field": key(ls), "direction": "desc"}]))[:3] == ["Гамма", "Бета", "Альфа"]

    bad = await client.get(
        "/api/tables/clients/rows",
        params={"filters": json.dumps([{"field": key(tariff), "op": "eq", "value": "Нет такого"}])},
        headers=h,
    )
    assert bad.status_code == 422  # значение не из списка
    # удалили поле — колонка исчезла и фильтровать по ней нельзя
    assert (await client.delete(f"/api/custom-fields/{points['id']}", headers=h)).status_code == 200
    meta2 = (await client.get("/api/tables/clients/meta", headers=h)).json()
    assert key(points) not in {c["key"] for c in meta2["columns"]}
    gone = await client.get(
        "/api/tables/clients/rows", params={"filters": json.dumps([{"field": key(points), "op": "is_null"}])}, headers=h
    )
    assert gone.status_code == 422
    gone_col = await client.get("/api/tables/clients/rows", params={"columns": key(points)}, headers=h)
    assert gone_col.status_code == 422

    # чужая компания не видит ни колонок, ни значений
    hb = await _headers(client, logins, "b_admin")
    meta_b = (await client.get("/api/tables/clients/meta", headers=hb)).json()
    assert not [c for c in meta_b["columns"] if c["key"].startswith("cf_")]
    assert (await client.get("/api/tables/clients/rows", params={"columns": key(ls)}, headers=hb)).status_code == 422


async def test_deals_and_equipment_tables_show_deal_and_client_fields(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    stages = await _stage_ids(client, hm)
    client_ls = await _field(client, hm, "ЛС", entity_type="client")
    deal_result = await _field(client, hm, "Результат", entity_type="deal")
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    won = await _add_deal(
        world, stages["Успех"], "a", "a_manager", amount=Decimal("100"), currency="UAH", closed_at=now, title="Продажа"
    )
    assert (await _put(client, hm, client_ls["id"], ids["ca"], "123456")).status_code == 200
    assert (await _put(client, hm, deal_result["id"], won, "Согласился")).status_code == 200
    created = await client.post(_items_url(won), json={"name": "Роутер", "price": 50}, headers=hm)
    assert created.status_code == 201, created.text

    deals_meta = {c["key"]: c for c in (await client.get("/api/tables/deals/meta", headers=hm)).json()["columns"]}
    own, linked = deals_meta[f"cf_{deal_result['id']}"], deals_meta[f"cf_{client_ls['id']}"]
    assert (own["label"], own["linked"], own["editable"]) == ("Результат", False, True)
    assert (linked["label"], linked["linked"], linked["editable"]) == ("Клиент: ЛС", True, False)

    cols = f"title,cf_{deal_result['id']},cf_{client_ls['id']}"
    deals = await client.get("/api/tables/deals/rows", params={"columns": cols}, headers=hm)
    assert deals.status_code == 200, deals.text
    row = deals.json()["items"][0]
    assert (row["title"], row[f"cf_{deal_result['id']}"], row[f"cf_{client_ls['id']}"]) == (
        "Продажа",
        "Согласился",
        "123456",
    )

    items_meta = {c["key"]: c for c in (await client.get("/api/tables/deal_items/meta", headers=hm)).json()["columns"]}
    assert items_meta[f"cf_{deal_result['id']}"]["label"] == "Сделка: Результат"
    assert items_meta[f"cf_{deal_result['id']}"]["linked"] is True
    assert items_meta[f"cf_{client_ls['id']}"]["label"] == "Клиент: ЛС"

    # Отчёт «кто что кому продал» с ЛС клиента и результатом сделки
    report = await client.get(
        "/api/tables/deal_items/rows",
        params={
            "columns": f"owner_name,client_name,cf_{client_ls['id']},name,price,cf_{deal_result['id']}",
            "filters": json.dumps([{"field": f"cf_{client_ls['id']}", "op": "eq", "value": "123456"}]),
        },
        headers=hm,
    )
    assert report.status_code == 200, report.text
    item = report.json()["items"][0]
    assert report.json()["total"] == 1
    assert (item["owner_name"], item["client_name"], item[f"cf_{client_ls['id']}"], item["name"], item["price"]) == (
        "a_manager",
        "Ромашка",
        "123456",
        "Роутер",
        50.0,
    )
    assert item[f"cf_{deal_result['id']}"] == "Согласился"
