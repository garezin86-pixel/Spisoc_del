# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_user_custom_table_links.py
"""Самостоятельные таблицы (Smart Tables, этап 4.4): колонки-связи с клиентом, сделкой, пользователем.

Главные риски: ссылка на чужую компанию, на удалённую или несуществующую запись, битый id в выдаче после
удаления связанной записи, обход проверки через неизменённое значение, лишние ошибки при правке соседних ячеек.
"""

import json
from datetime import datetime, timezone

from src.models.client import ClientModel
from src.models.deal import DealModel
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)
from tests.test_deal_items import _add_deal, _stage_ids

URL = "/api/user-custom-tables"
TABLES = "/api/tables"


def _col(name: str, data_type: str = "text", **extra) -> dict:
    return {"name": name, "data_type": data_type} | extra


async def _calls_table(client, h, name="Обзвон") -> dict:
    resp = await client.post(
        URL,
        json={
            "name": name,
            "columns": [_col("Заметка"), _col("Клиент", "client"), _col("Сделка", "deal"), _col("Менеджер", "user")],
        },
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    table = resp.json()
    table["k"] = {c["name"]: c["key"] for c in table["columns"]}
    return table


def _rows(table_id: int) -> str:
    return f"{URL}/{table_id}/rows"


async def _add(client, h, table, expect=201, **by_name):
    values = {table["k"][name]: value for name, value in by_name.items()}
    resp = await client.post(_rows(table["id"]), json={"values": values}, headers=h)
    assert resp.status_code == expect, resp.text
    return resp.json()


async def _query(client, h, table, **params):
    query = {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in params.items()}
    resp = await client.get(f"{TABLES}/uct_{table['id']}/rows", params=query, headers=h)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _open_deal(client, world_, h, title="Сделка", ws="a", owner="owner") -> int:
    stages = await _stage_ids(client, h)
    return await _add_deal(world_, stages["Новая"], ws, owner, title=title)


# ── описание ─────────────────────────────────────────────────────────────────
async def test_link_columns_and_meta(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    bad = await client.post(URL, json={"name": "Т", "columns": [_col("К", "client", options=["x"])]}, headers=h)
    assert bad.status_code == 422  # у связи нет списка значений
    table = await _calls_table(client, h)
    k = table["k"]
    assert [c["data_type"] for c in table["columns"]] == ["text", "client", "deal", "user"]

    meta = (await client.get(f"{TABLES}/uct_{table['id']}/meta", headers=h)).json()
    by_key = {c["key"]: c for c in meta["columns"]}
    for name, kind in (("Клиент", "client"), ("Сделка", "deal"), ("Менеджер", "user")):
        ref, label = by_key[k[name]], by_key[f"{k[name]}_name"]
        assert (ref["type"], ref["label"], ref["editable"], ref["linked"]) == (kind, f"{name} (id)", True, False)
        assert ref["ops"] == ["eq", "ne", "in", "is_null", "not_null"]
        assert (label["type"], label["label"], label["editable"], label["linked"]) == ("text", name, False, True)
    assert meta["default_columns"] == [
        k["Заметка"],
        f"{k['Клиент']}_name",
        f"{k['Сделка']}_name",
        f"{k['Менеджер']}_name",
    ]


# ── запись связей ────────────────────────────────────────────────────────────
async def test_row_with_links_and_names_in_table(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "owner")
    table = await _calls_table(client, h)
    k = table["k"]
    deal_id = await _open_deal(client, world, h, title="Продажа роутера")

    row = await _add(
        client, h, table, Заметка="Позвонить", Клиент=ids["ca"], Сделка=str(deal_id), Менеджер=ids["a_manager"]
    )
    assert row["values"][k["Клиент"]] == ids["ca"] and row["values"][k["Сделка"]] == deal_id  # строка из цифр → число
    assert row["values"][k["Менеджер"]] == ids["a_manager"]
    await _add(client, h, table, Заметка="Без связей")

    body = await _query(client, h, table)
    first, second = body["items"]
    assert first[f"{k['Клиент']}_name"] == "Ромашка" and first[f"{k['Сделка']}_name"] == "Продажа роутера"
    assert first[f"{k['Менеджер']}_name"] == "a_manager"
    assert second[f"{k['Клиент']}_name"] is None and second[f"{k['Менеджер']}_name"] is None  # связи нет — None
    ids_view = await _query(client, h, table, columns=f"{k['Клиент']},{k['Сделка']}")
    assert ids_view["items"][0][k["Клиент"]] == ids["ca"] and ids_view["items"][1][k["Клиент"]] is None


async def test_link_validation(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "owner")
    hb = await _headers(client, logins, "b_admin")
    table = await _calls_table(client, h)
    deal_b = await _open_deal(client, world, hb, title="Чужая", ws="b", owner="b_admin")
    deal_a = await _open_deal(client, world, h, title="Своя")

    async def code(name, value) -> int:
        return (
            await client.post(_rows(table["id"]), json={"values": {table["k"][name]: value}}, headers=h)
        ).status_code

    assert await code("Клиент", 99999) == 422  # такого клиента нет
    assert await code("Клиент", ids["cb"]) == 422  # клиент чужой компании
    assert await code("Сделка", deal_b) == 422  # сделка чужой компании
    assert await code("Менеджер", ids["b_admin"]) == 422  # пользователь чужой компании
    assert await code("Сделка", 99999) == 422
    for bad in (True, 0, -1, 1.5, "abc", "1.5", "１", [ids["ca"]], {"id": ids["ca"]}, 2**31):
        assert await code("Клиент", bad) == 422, bad
    message = (await client.post(_rows(table["id"]), json={"values": {table["k"]["Клиент"]: 99999}}, headers=h)).json()
    assert message["detail"] == "Колонка «Клиент»: Клиент с id 99999 не найден"

    maker = world[0]
    async with maker() as s:  # удалённый клиент и удалённая сделка
        gone = ClientModel(
            name="Удалённый", workspace_id=ids["a"], owner_id=ids["owner"], deleted_at=datetime.now(timezone.utc)
        )
        s.add(gone)
        deal = await s.get(DealModel, deal_a)
        deal.deleted_at = datetime.now(timezone.utc)
        await s.commit()
        gone_id = gone.id
    assert await code("Клиент", gone_id) == 422
    assert await code("Сделка", deal_a) == 422
    assert (await client.get(_rows(table["id"]), headers=h)).json()["total"] == 0  # ничего не сохранилось


# ── фильтры и сортировка по связям ───────────────────────────────────────────
async def test_filter_and_sort_by_links(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "owner")
    table = await _calls_table(client, h)
    k = table["k"]
    async with maker() as s:
        extra = [ClientModel(name=n, workspace_id=ids["a"], owner_id=ids["owner"]) for n in ("Альфа", "Бета")]
        s.add_all(extra)
        await s.commit()
        alpha, beta = (c.id for c in extra)
    await _add(client, h, table, Заметка="1", Клиент=ids["ca"])
    await _add(client, h, table, Заметка="2", Клиент=alpha)
    await _add(client, h, table, Заметка="3", Клиент=beta)
    await _add(client, h, table, Заметка="4")

    def notes(resp):
        return [r[k["Заметка"]] for r in resp["items"]]

    async def where(*conditions, **extra_params):
        return notes(await _query(client, h, table, filters=list(conditions), **extra_params))

    assert await where({"field": k["Клиент"], "op": "eq", "value": alpha}) == ["2"]
    assert await where({"field": k["Клиент"], "op": "in", "value": [alpha, beta]}) == ["2", "3"]
    assert await where({"field": k["Клиент"], "op": "ne", "value": alpha}) == [
        "1",
        "3",
        "4",
    ]  # «не равно» не теряет пустые
    assert await where({"field": k["Клиент"], "op": "is_null"}) == ["4"]
    assert await where({"field": k["Клиент"], "op": "not_null"}) == ["1", "2", "3"]
    assert await where({"field": f"{k['Клиент']}_name", "op": "contains", "value": "Аль"}) == ["2"]
    assert await where({"field": f"{k['Клиент']}_name", "op": "eq", "value": "Бета"}) == ["3"]
    by_name = notes(await _query(client, h, table, sort=[{"field": f"{k['Клиент']}_name"}]))
    assert by_name == ["2", "3", "1", "4"]  # Альфа, Бета, Ромашка; без связи — в конце

    async def code(**params) -> int:
        query = {key: json.dumps(v) if isinstance(v, (list, dict)) else v for key, v in params.items()}
        return (await client.get(f"{TABLES}/uct_{table['id']}/rows", params=query, headers=h)).status_code

    assert await code(filters=[{"field": k["Клиент"], "op": "contains", "value": "1"}]) == 422  # id — не текст
    assert await code(filters=[{"field": k["Клиент"], "op": "eq", "value": "abc"}]) == 422
    assert await code(filters=[{"field": k["Клиент"], "op": "gt", "value": 1}]) == 422


# ── целостность ссылок ───────────────────────────────────────────────────────
async def test_deleted_and_renamed_targets(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "owner")
    table = await _calls_table(client, h)
    k = table["k"]
    deal_id = await _open_deal(client, world, h, title="Продажа")
    await _add(client, h, table, Заметка="Связана", Клиент=ids["ca"], Сделка=deal_id)
    await _add(client, h, table, Заметка="Пустая")

    async def view():
        row = (await _query(client, h, table))["items"]
        return row[0], row[1]

    first, empty = await view()
    assert first[f"{k['Клиент']}_name"] == "Ромашка" and first[f"{k['Сделка']}_name"] == "Продажа"

    async with maker() as s:  # переименовали клиента и сделку
        client_row = await s.get(ClientModel, ids["ca"])
        client_row.name = "Ромашка 2"
        deal = await s.get(DealModel, deal_id)
        deal.title = "Продажа 2"
        await s.commit()
    first, _ = await view()
    assert first[f"{k['Клиент']}_name"] == "Ромашка 2" and first[f"{k['Сделка']}_name"] == "Продажа 2"  # название живое

    async with maker() as s:  # удалили клиента и сделку
        client_row = await s.get(ClientModel, ids["ca"])
        client_row.deleted_at = datetime.now(timezone.utc)
        deal = await s.get(DealModel, deal_id)
        deal.deleted_at = datetime.now(timezone.utc)
        await s.commit()
    first, empty = await view()
    assert first[f"{k['Клиент']}_name"] == "(удалён)" and first[f"{k['Сделка']}_name"] == "(удалён)"
    assert empty[f"{k['Клиент']}_name"] is None  # у строки без связи по-прежнему пусто
    ids_view = await _query(client, h, table, columns=k["Клиент"])
    assert ids_view["items"][0][k["Клиент"]] == ids["ca"]  # id сохранён: связь не «битая», а помечена удалённой
    marked = await _query(
        client,
        h,
        table,
        filters=[{"field": f"{k['Клиент']}_name", "op": "eq", "value": "(удалён)"}],
        columns=k["Заметка"],
    )
    assert [r[k["Заметка"]] for r in marked["items"]] == ["Связана"]  # такие строки легко найти

    # правка соседних ячеек не ломается из-за удалённой связи; та же ссылка без изменений тоже не перепроверяется
    row_id = first["_id"]
    url = f"{_rows(table['id'])}/{row_id}"
    assert (await client.patch(url, json={"values": {k["Заметка"]: "Новая заметка"}}, headers=h)).status_code == 200
    same = await client.patch(url, json={"values": {k["Клиент"]: ids["ca"], k["Заметка"]: "Ещё"}}, headers=h)
    assert same.status_code == 200
    # а выбрать удалённого клиента заново нельзя
    other = await client.patch(url, json={"values": {k["Сделка"]: deal_id}}, headers=h)
    assert other.status_code == 200  # значение не менялось
    async with maker() as s:
        another = ClientModel(
            name="Другой", workspace_id=ids["a"], owner_id=ids["owner"], deleted_at=datetime.now(timezone.utc)
        )
        s.add(another)
        await s.commit()
        another_id = another.id
    assert (await client.patch(url, json={"values": {k["Клиент"]: another_id}}, headers=h)).status_code == 422


async def test_update_and_clear_link(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")  # в общей таблице связи правит любой
    table = await _calls_table(client, h)
    k = table["k"]
    async with maker() as s:
        second = ClientModel(name="Второй", workspace_id=ids["a"], owner_id=ids["owner"])
        s.add(second)
        await s.commit()
        second_id = second.id
    row = await _add(client, h, table, Клиент=ids["ca"])
    url = f"{_rows(table['id'])}/{row['id']}"

    moved = await client.patch(
        url, json={"values": {k["Клиент"]: second_id}, "version": row["updated_at"]}, headers=other_h
    )
    assert moved.status_code == 200 and moved.json()["values"][k["Клиент"]] == second_id
    assert (await _query(client, h, table))["items"][0][f"{k['Клиент']}_name"] == "Второй"
    assert (await client.patch(url, json={"values": {k["Клиент"]: None}}, headers=h)).json()["values"][
        k["Клиент"]
    ] is None
    again = await client.patch(url, json={"values": {k["Клиент"]: ids["ca"]}}, headers=h)
    assert again.status_code == 200
    assert (await client.patch(url, json={"values": {k["Клиент"]: ""}}, headers=h)).json()["values"][
        k["Клиент"]
    ] is None
    cleared = (await _query(client, h, table))["items"][0]
    assert cleared[f"{k['Клиент']}_name"] is None  # после очистки названия нет

    # колонка с названием — только для показа: писать в неё нельзя
    assert (await client.patch(url, json={"values": {f"{k['Клиент']}_name": "X"}}, headers=h)).status_code == 422


async def test_links_do_not_leak_between_companies(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_manager")
    hb = await _headers(client, logins, "b_admin")
    table_a = await _calls_table(client, ha, "Обзвон A")
    table_b = await _calls_table(client, hb, "Обзвон B")
    await _add(client, ha, table_a, Заметка="A", Клиент=ids["ca"])
    await _add(client, hb, table_b, Заметка="B", Клиент=ids["cb"])
    await _add(client, hb, table_b, expect=422, Клиент=ids["ca"])  # B не может сослаться на клиента A

    row_b = (await _query(client, hb, table_b))["items"][0]
    assert row_b[f"{table_b['k']['Клиент']}_name"] == "Лютик"
    row_a = (await _query(client, ha, table_a))["items"][0]
    assert row_a[f"{table_a['k']['Клиент']}_name"] == "Ромашка"
