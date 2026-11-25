# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_user_custom_table_query.py
"""Самостоятельные таблицы (Smart Tables, этап 4.3): каждая таблица — источник `uct_<id>` в общем движке.

Главные риски: чужие личные таблицы в списке источников, чтение чужой компании, строки другой таблицы или
удалённые строки в выдаче, обход реестра колонок, потеря версии строки для защиты от одновременной правки.
"""

import json

from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)

URL = "/api/user-custom-tables"
TABLES = "/api/tables"


def _col(name: str, data_type: str = "text", **extra) -> dict:
    return {"name": name, "data_type": data_type} | extra


async def _warehouse(client, h, name="Склад", **extra) -> dict:
    resp = await client.post(
        URL,
        json={
            "name": name,
            "columns": [
                _col("Название"),
                _col("Количество", "number"),
                _col("Поступило", "date"),
                _col("На складе", "boolean"),
                _col("Состояние", "select", options=["Новый", "БУ", "Сломан"]),
            ],
        }
        | extra,
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    table = resp.json()
    table["k"] = {c["name"]: c["key"] for c in table["columns"]}
    return table


async def _add(client, h, table, **by_name) -> dict:
    values = {table["k"][name]: value for name, value in by_name.items()}
    resp = await client.post(f"{URL}/{table['id']}/rows", json={"values": values}, headers=h)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _rows(client, h, table, **params):
    query = {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in params.items()}
    resp = await client.get(f"{TABLES}/uct_{table['id']}/rows", params=query, headers=h)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _stock(client, h) -> dict:
    """Склад с четырьмя строками для проверки фильтров."""
    table = await _warehouse(client, h)
    await _add(
        client,
        h,
        table,
        Название="Роутер X",
        Количество=15,
        Поступило="2026-03-01",
        Состояние="Новый",
        **{"На складе": True},
    )
    await _add(
        client,
        h,
        table,
        Название="Роутер Y",
        Количество=3,
        Поступило="2026-06-01",
        Состояние="БУ",
        **{"На складе": False},
    )
    await _add(
        client,
        h,
        table,
        Название="ONU Z",
        Количество=40,
        Поступило="2026-09-01",
        Состояние="Новый",
        **{"На складе": True},
    )
    await _add(client, h, table, Название="Кабель")  # остальное пусто
    return table


# ── список источников и описание ─────────────────────────────────────────────
async def test_sources_list_visible_tables(client, world):
    _, _, logins = world
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    shared = await _warehouse(client, owner_h, "Общий склад")
    private = await _warehouse(client, owner_h, "Личный склад", visibility="private")

    def keys(resp):
        return {s["key"]: s["label"] for s in resp.json()}

    own = keys(await client.get(TABLES, headers=owner_h))
    assert own[f"uct_{shared['id']}"] == "Общий склад" and own[f"uct_{private['id']}"] == "Личный склад"
    assert {"clients", "deals", "deal_items"} <= set(own)
    seen_by_other = keys(await client.get(TABLES, headers=other_h))
    assert f"uct_{shared['id']}" in seen_by_other and f"uct_{private['id']}" not in seen_by_other
    manager_h = await _headers(client, logins, "a_manager")
    assert f"uct_{private['id']}" in keys(await client.get(TABLES, headers=manager_h))  # admin и manager видят личные

    # чужая личная таблица неотличима от несуществующей
    for path in ("meta", "rows"):
        assert (await client.get(f"{TABLES}/uct_{private['id']}/{path}", headers=other_h)).status_code == 404

    hb = await _headers(client, logins, "b_admin")
    assert f"uct_{shared['id']}" not in keys(await client.get(TABLES, headers=hb))
    assert (await client.get(f"{TABLES}/uct_{shared['id']}/rows", headers=hb)).status_code == 404

    assert (await client.delete(f"{URL}/{shared['id']}", headers=owner_h)).status_code == 200
    assert f"uct_{shared['id']}" not in keys(await client.get(TABLES, headers=owner_h))
    assert (await client.get(f"{TABLES}/uct_{shared['id']}/rows", headers=owner_h)).status_code == 404


async def test_bad_source_keys(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _warehouse(client, h)
    for key in ("uct_abc", "uct_0", "uct_999999", f"uct_0{table['id']}", "uct_", "uct_-1", "uct_１"):
        assert (await client.get(f"{TABLES}/{key}/meta", headers=h)).status_code == 404, key
        assert (await client.get(f"{TABLES}/{key}/rows", headers=h)).status_code == 404, key


async def test_meta_of_user_table(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _warehouse(client, h, "Склад")
    k = table["k"]
    meta = (await client.get(f"{TABLES}/uct_{table['id']}/meta", headers=h)).json()
    assert meta["source"] == f"uct_{table['id']}" and meta["label"] == "Склад"
    keys = [c["key"] for c in meta["columns"]]
    assert keys[:5] == [k["Название"], k["Количество"], k["Поступило"], k["На складе"], k["Состояние"]]
    assert keys[5:] == ["id", "created_by_name", "created_at", "updated_at"]  # служебные идут после
    by_key = {c["key"]: c for c in meta["columns"]}
    assert by_key[k["Количество"]]["type"] == "number" and by_key[k["Количество"]]["editable"] is True
    assert by_key[k["Состояние"]]["options"] == ["Новый", "БУ", "Сломан"]
    assert by_key[k["На складе"]]["ops"] == ["eq"] and "contains" in by_key[k["Название"]]["ops"]
    assert by_key["created_by_name"]["linked"] is True and by_key["id"]["editable"] is False
    assert meta["default_columns"] == keys[:5]  # по умолчанию — пользовательские колонки

    renamed = await client.patch(f"{URL}/{table['id']}/columns/{k['Название'][1:]}", json={"name": "Модель"}, headers=h)
    assert renamed.status_code == 200
    meta2 = (await client.get(f"{TABLES}/uct_{table['id']}/meta", headers=h)).json()
    assert {c["key"]: c["label"] for c in meta2["columns"]}[k["Название"]] == "Модель"  # ключ тот же, подпись новая


# ── строки, фильтры, сортировка ──────────────────────────────────────────────
async def test_rows_default_and_filters(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _stock(client, h)
    k = table["k"]

    body = await _rows(client, h, table)
    assert body["total"] == 4 and body["columns"] == [
        k[n] for n in ("Название", "Количество", "Поступило", "На складе", "Состояние")
    ]
    first = body["items"][0]
    assert (
        first[k["Название"]] == "Роутер X" and first[k["Количество"]] == 15.0 and first[k["Поступило"]] == "2026-03-01"
    )
    assert first[k["На складе"]] is True and first[k["Состояние"]] == "Новый"
    assert body["items"][3][k["Количество"]] is None  # пустые ячейки — None
    assert [r[k["Название"]] for r in body["items"]] == [
        "Роутер X",
        "Роутер Y",
        "ONU Z",
        "Кабель",
    ]  # порядок добавления

    def names(resp):
        return [r[k["Название"]] for r in resp["items"]]

    async def where(*conditions, **extra):
        return names(await _rows(client, h, table, filters=list(conditions), **extra))

    assert await where({"field": k["Название"], "op": "contains", "value": "Роутер"}) == ["Роутер X", "Роутер Y"]
    assert await where({"field": k["Название"], "op": "contains", "value": "onu"}) == ["ONU Z"]  # регистр не важен
    assert await where({"field": k["Название"], "op": "contains", "value": "ONU"}) == ["ONU Z"]
    assert await where({"field": k["Название"], "op": "eq", "value": "Кабель"}) == ["Кабель"]
    assert await where({"field": k["Количество"], "op": "gte", "value": 15}) == ["Роутер X", "ONU Z"]
    assert await where({"field": k["Количество"], "op": "lt", "value": 10}) == ["Роутер Y"]
    assert await where({"field": k["Поступило"], "op": "gte", "value": "2026-05-01"}) == ["Роутер Y", "ONU Z"]
    assert await where({"field": k["Состояние"], "op": "in", "value": ["БУ", "Сломан"]}) == ["Роутер Y"]
    assert await where({"field": k["Состояние"], "op": "eq", "value": "Новый"}) == ["Роутер X", "ONU Z"]
    assert await where({"field": k["На складе"], "op": "eq", "value": False}) == ["Роутер Y"]
    assert await where({"field": k["Количество"], "op": "is_null"}) == ["Кабель"]
    assert await where({"field": k["Количество"], "op": "not_null"}) == ["Роутер X", "Роутер Y", "ONU Z"]
    assert await where(
        {"field": k["Состояние"], "op": "eq", "value": "Новый"}, {"field": k["Количество"], "op": "gt", "value": 20}
    ) == ["ONU Z"]  # условия объединяются через И

    desc = await _rows(client, h, table, sort=[{"field": k["Количество"], "direction": "desc"}])
    assert names(desc) == ["ONU Z", "Роутер X", "Роутер Y", "Кабель"]  # пустые в конце
    asc = await _rows(client, h, table, sort=[{"field": k["Поступило"], "direction": "asc"}])
    assert names(asc)[:3] == ["Роутер X", "Роутер Y", "ONU Z"]
    page = await _rows(client, h, table, size=3, page=2)
    assert page["total"] == 4 and page["pages"] == 2 and names(page) == ["Кабель"]
    picked = await _rows(client, h, table, columns=f"{k['Название']},id,created_by_name")
    assert picked["items"][0]["created_by_name"] == "owner" and picked["columns"] == [
        k["Название"],
        "id",
        "created_by_name",
    ]


async def test_filters_reject_bad_input(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _stock(client, h)
    other = await _warehouse(client, h, "Другой склад")
    k = table["k"]

    async def code(**params) -> int:
        query = {key: json.dumps(v) if isinstance(v, (list, dict)) else v for key, v in params.items()}
        return (await client.get(f"{TABLES}/uct_{table['id']}/rows", params=query, headers=h)).status_code

    assert (
        await code(filters=[{"field": k["Количество"], "op": "contains", "value": "1"}]) == 422
    )  # операция не для типа
    assert await code(filters=[{"field": k["Количество"], "op": "gt", "value": "abc"}]) == 422
    assert await code(filters=[{"field": k["Состояние"], "op": "eq", "value": "Нет такого"}]) == 422  # не из списка
    assert await code(filters=[{"field": k["На складе"], "op": "eq", "value": "да"}]) == 422
    assert await code(filters=[{"field": "c99999", "op": "is_null"}]) == 422
    assert await code(filters=[{"field": "workspace_id", "op": "eq", "value": 1}]) == 422
    assert await code(columns="table_id") == 422
    # колонка соседней таблицы здесь недоступна
    foreign = other["k"]["Название"]
    assert await code(columns=foreign) == 422
    assert await code(filters=[{"field": foreign, "op": "is_null"}]) == 422
    assert await code(sort=[{"field": foreign}]) == 422
    assert await code(filters=[{"field": k["Название"], "op": "contains", "value": "x"}]) == 200


# ── что видно в выдаче ───────────────────────────────────────────────────────
async def test_only_own_live_rows_and_columns(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _stock(client, h)
    other = await _warehouse(client, h, "Другой склад")
    k = table["k"]
    await _add(client, h, other, Название="Из другой таблицы")

    assert (await _rows(client, h, table))["total"] == 4  # строки соседней таблицы не смешиваются
    row_id = (await _rows(client, h, table, columns="id"))["items"][3]["_id"]
    assert (await client.delete(f"{URL}/{table['id']}/rows/{row_id}", headers=h)).status_code == 200
    body = await _rows(client, h, table)
    assert body["total"] == 3 and "Кабель" not in [r[k["Название"]] for r in body["items"]]  # удалённая строка скрыта

    col_id = int(k["Количество"][1:])
    assert (await client.delete(f"{URL}/{table['id']}/columns/{col_id}", headers=h)).status_code == 200
    after = await _rows(client, h, table)
    assert k["Количество"] not in after["columns"] and k["Количество"] not in after["items"][0]
    gone = await client.get(
        f"{TABLES}/uct_{table['id']}/rows",
        params={"filters": json.dumps([{"field": k["Количество"], "op": "is_null"}])},
        headers=h,
    )
    assert gone.status_code == 422  # по удалённой колонке фильтровать нельзя


async def test_isolation_of_values_between_companies(client, world):
    _, _, logins = world
    ha = await _headers(client, logins, "a_manager")
    hb = await _headers(client, logins, "b_admin")
    table_a = await _stock(client, ha)
    table_b = await _warehouse(client, hb, "Склад B")
    await _add(client, hb, table_b, Название="Только B")

    assert (await _rows(client, ha, table_a))["total"] == 4
    only_b = await _rows(client, hb, table_b)
    assert [r[table_b["k"]["Название"]] for r in only_b["items"]] == ["Только B"]
    assert (await client.get(f"{TABLES}/uct_{table_b['id']}/rows", headers=ha)).status_code == 404
    keys = {s["key"] for s in (await client.get(TABLES, headers=ha)).json()}
    assert f"uct_{table_b['id']}" not in keys


async def test_version_from_table_query_works_as_edit_token(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    table = await _stock(client, h)
    k = table["k"]
    items = (await _rows(client, h, table, columns=f"id,{k['Количество']}"))["items"]
    item = items[1]  # Роутер Y
    assert item["_version"]
    url = f"{URL}/{table['id']}/rows/{item['_id']}"

    first = await client.patch(url, json={"values": {k["Количество"]: 2}, "version": item["_version"]}, headers=h)
    assert first.status_code == 200, first.text  # _version из таблицы подходит как version для правки строки
    stale = await client.patch(url, json={"values": {k["Количество"]: 1}, "version": item["_version"]}, headers=other_h)
    assert stale.status_code == 409
    refreshed = (await _rows(client, h, table, columns=k["Количество"]))["items"][1]
    assert refreshed[k["Количество"]] == 2.0 and refreshed["_version"] != item["_version"]
