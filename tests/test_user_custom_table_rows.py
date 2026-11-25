# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_user_custom_table_rows.py
"""Самостоятельные таблицы (Smart Tables, этап 4.2): строки и ячейки.

Главные риски: правка без прав (личные таблицы), значение не того типа, затирание чужой правки при совместной
работе, потеря значений, утечка между компаниями.
"""

from sqlalchemy import select

from src.models.audit import AuditLog
from src.models.user_custom_table import UserCustomTableCellModel, UserCustomTableRowModel
from src.services import user_custom_table_row_service
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)

URL = "/api/user-custom-tables"


def _col(name: str, data_type: str = "text", **extra) -> dict:
    return {"name": name, "data_type": data_type} | extra


async def _warehouse(client, h, **extra) -> dict:
    """Таблица «Склад» со всеми типами колонок."""
    resp = await client.post(
        URL,
        json={
            "name": "Склад",
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
    table["k"] = {c["name"]: c["key"] for c in table["columns"]}  # название -> ключ c<id>
    return table


def _rows(table_id: int) -> str:
    return f"{URL}/{table_id}/rows"


# ── добавление, чтение, правка, удаление ─────────────────────────────────────
async def test_row_lifecycle_by_plain_user_in_shared_table(client, world):
    _, ids, logins = world
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")  # не владелец, не manager
    table = await _warehouse(client, owner_h)
    k = table["k"]

    created = await client.post(
        _rows(table["id"]),
        json={
            "values": {
                k["Название"]: "  Роутер X  ",
                k["Количество"]: "15",
                k["Поступило"]: "2026-11-23",
                k["На складе"]: True,
                k["Состояние"]: "Новый",
            }
        },
        headers=other_h,  # в общей таблице строки добавляет любой
    )
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["created_by_id"] == ids["other"] and row["updated_at"]
    assert row["values"] == {
        k["Название"]: "Роутер X",
        k["Количество"]: 15.0,
        k["Поступило"]: "2026-11-23",
        k["На складе"]: True,
        k["Состояние"]: "Новый",
    }

    # владелец правит чужую строку: меняются только переданные колонки
    patched = await client.patch(
        f"{_rows(table['id'])}/{row['id']}",
        json={"values": {k["Количество"]: 14, k["Состояние"]: "БУ"}},
        headers=owner_h,
    )
    assert patched.status_code == 200, patched.text
    values = patched.json()["values"]
    assert values[k["Количество"]] == 14.0 and values[k["Состояние"]] == "БУ" and values[k["Название"]] == "Роутер X"

    # очистка: null и пустая строка
    cleared = await client.patch(
        f"{_rows(table['id'])}/{row['id']}", json={"values": {k["Название"]: None, k["Состояние"]: ""}}, headers=other_h
    )
    assert cleared.json()["values"][k["Название"]] is None and cleared.json()["values"][k["Состояние"]] is None
    false_kept = await client.patch(
        f"{_rows(table['id'])}/{row['id']}", json={"values": {k["На складе"]: False}}, headers=other_h
    )
    assert false_kept.json()["values"][k["На складе"]] is False  # false — значение, а не очистка

    listing = (await client.get(_rows(table["id"]), headers=other_h)).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == row["id"]
    assert set(listing["items"][0]["values"]) == set(k.values())  # все колонки, пустые — null

    assert (await client.delete(f"{_rows(table['id'])}/{row['id']}", headers=other_h)).status_code == 200
    assert (await client.get(_rows(table["id"]), headers=owner_h)).json()["items"] == []
    assert (await client.delete(f"{_rows(table['id'])}/{row['id']}", headers=other_h)).status_code == 404


async def test_empty_row_paging_and_order(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _warehouse(client, h)
    k = table["k"]
    empty = await client.post(_rows(table["id"]), json={}, headers=h)  # пустая строка допустима
    assert empty.status_code == 201 and all(v is None for v in empty.json()["values"].values())
    for i in range(4):
        await client.post(_rows(table["id"]), json={"values": {k["Название"]: f"Т{i}"}}, headers=h)

    page1 = (await client.get(_rows(table["id"]), params={"size": 2}, headers=h)).json()
    page3 = (await client.get(_rows(table["id"]), params={"size": 2, "page": 3}, headers=h)).json()
    assert page1["total"] == 5 and page1["pages"] == 3 and len(page1["items"]) == 2
    assert [r["values"][k["Название"]] for r in page3["items"]] == ["Т3"]  # порядок добавления
    assert (await client.get(_rows(table["id"]), params={"size": 500}, headers=h)).status_code == 422
    assert (await client.get(_rows(table["id"]), params={"page": 0}, headers=h)).status_code == 422


async def test_value_validation(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _warehouse(client, h)
    k, tid = table["k"], table["id"]

    async def code(values) -> int:
        return (await client.post(_rows(tid), json={"values": values}, headers=h)).status_code

    assert await code({"c99999": "x"}) == 422  # такой колонки нет
    assert await code({"название": "x"}) == 422  # ключ — это c<id>, а не название
    assert await code({k["Количество"]: "abc"}) == 422
    assert await code({k["Количество"]: True}) == 422
    assert await code({k["Количество"]: 1.23456}) == 422  # больше 4 знаков
    assert await code({k["Количество"]: 10**14}) == 422
    assert await code({k["Поступило"]: "23.11.2026"}) == 422
    assert await code({k["Поступило"]: "2026-02-30"}) == 422
    assert await code({k["На складе"]: "true"}) == 422
    assert await code({k["На складе"]: 1}) == 422
    assert await code({k["Состояние"]: "Неизвестно"}) == 422  # нет в списке
    assert await code({k["Название"]: "x" * 2001}) == 422
    assert await code({k["Название"]: 123}) == 422
    assert await code({k["Название"]: "x" * 2000, k["Количество"]: 0, k["На складе"]: False}) == 201
    assert (
        (await client.post(_rows(tid), json={"values": {k["Количество"]: "x"}}, headers=h))
        .json()["detail"]
        .startswith("Колонка «Количество»")
    )
    first = (await client.get(_rows(tid), headers=h)).json()["total"]
    assert first == 1  # отклонённые строки не сохранились


async def test_row_limit(client, world, monkeypatch):
    _, _, logins = world
    monkeypatch.setattr(user_custom_table_row_service, "MAX_ROWS_PER_TABLE", 2)
    h = await _headers(client, logins, "owner")
    table = await _warehouse(client, h)
    for _ in range(2):
        assert (await client.post(_rows(table["id"]), json={}, headers=h)).status_code == 201
    assert (await client.post(_rows(table["id"]), json={}, headers=h)).status_code == 409


# ── права и изоляция ─────────────────────────────────────────────────────────
async def test_private_table_rows_only_for_owner_and_managers(client, world):
    _, _, logins = world
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    manager_h = await _headers(client, logins, "a_manager")
    table = await _warehouse(client, owner_h, visibility="private")
    k, tid = table["k"], table["id"]
    row = (await client.post(_rows(tid), json={"values": {k["Название"]: "Секрет"}}, headers=owner_h)).json()

    assert (await client.get(_rows(tid), headers=other_h)).status_code == 404
    assert (await client.post(_rows(tid), json={}, headers=other_h)).status_code == 404
    assert (await client.patch(f"{_rows(tid)}/{row['id']}", json={"values": {}}, headers=other_h)).status_code == 404
    assert (await client.delete(f"{_rows(tid)}/{row['id']}", headers=other_h)).status_code == 404

    assert (await client.post(_rows(tid), json={}, headers=manager_h)).status_code == 201
    assert (await client.get(_rows(tid), headers=manager_h)).json()["total"] == 2

    # стала общей — строки доступны всем
    await client.patch(f"{URL}/{tid}", json={"visibility": "shared"}, headers=owner_h)
    assert (await client.get(_rows(tid), headers=other_h)).json()["total"] == 2
    assert (await client.post(_rows(tid), json={}, headers=other_h)).status_code == 201
    assert (await client.get(_rows(tid))).status_code in (401, 403)


async def test_isolation_between_companies_and_tables(client, world):
    _, _, logins = world
    ha = await _headers(client, logins, "a_manager")
    table = await _warehouse(client, ha)
    k, tid = table["k"], table["id"]
    row = (await client.post(_rows(tid), json={"values": {k["Название"]: "A"}}, headers=ha)).json()

    hb = await _headers(client, logins, "b_admin")
    assert (await client.get(_rows(tid), headers=hb)).status_code == 404
    assert (await client.post(_rows(tid), json={}, headers=hb)).status_code == 404
    assert (await client.patch(f"{_rows(tid)}/{row['id']}", json={"values": {}}, headers=hb)).status_code == 404
    assert (await client.delete(f"{_rows(tid)}/{row['id']}", headers=hb)).status_code == 404

    # строка принадлежит своей таблице: через другую таблицу своей компании её не достать
    other = await _warehouse(client, ha)
    assert (await client.patch(f"{_rows(other['id'])}/{row['id']}", json={"values": {}}, headers=ha)).status_code == 404
    assert (await client.delete(f"{_rows(other['id'])}/{row['id']}", headers=ha)).status_code == 404
    assert (await client.get(_rows(other["id"]), headers=ha)).json()["total"] == 0


# ── совместная работа ────────────────────────────────────────────────────────
async def test_optimistic_lock_between_two_users(client, world):
    _, _, logins = world
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    table = await _warehouse(client, owner_h)
    k, tid = table["k"], table["id"]
    row = (
        await client.post(_rows(tid), json={"values": {k["Название"]: "Роутер", k["Количество"]: 5}}, headers=owner_h)
    ).json()
    url = f"{_rows(tid)}/{row['id']}"
    v0 = row["updated_at"]

    # оба открыли строку на версии v0; первый сохраняет
    first = await client.patch(url, json={"values": {k["Количество"]: 4}, "version": v0}, headers=owner_h)
    assert first.status_code == 200 and first.json()["updated_at"] != v0
    v1 = first.json()["updated_at"]

    # второй пытается сохранить на устаревшей версии — отказ, правка первого цела
    stale = await client.patch(url, json={"values": {k["Название"]: "Другое"}, "version": v0}, headers=other_h)
    assert stale.status_code == 409
    current = (await client.get(_rows(tid), headers=other_h)).json()["items"][0]
    assert current["values"][k["Количество"]] == 4.0 and current["values"][k["Название"]] == "Роутер"

    # обновил данные — сохраняет на свежей версии; версия снова новая
    ok = await client.patch(url, json={"values": {k["Название"]: "Другое"}, "version": v1}, headers=other_h)
    assert ok.status_code == 200 and ok.json()["updated_at"] != v1
    assert ok.json()["values"][k["Количество"]] == 4.0  # изменение первого сохранилось

    # без version — последняя запись побеждает; версия с «Z» и без часового пояса понимается одинаково
    assert (await client.patch(url, json={"values": {k["Количество"]: 1}}, headers=owner_h)).status_code == 200
    latest = (await client.get(_rows(tid), headers=owner_h)).json()["items"][0]["updated_at"]
    assert (await client.patch(url, json={"values": {}, "version": latest}, headers=owner_h)).status_code == 200
    assert (await client.patch(url, json={"values": {}, "version": "не дата"}, headers=owner_h)).status_code == 422


async def test_noop_patch_keeps_version(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _warehouse(client, h)
    k, tid = table["k"], table["id"]
    row = (
        await client.post(_rows(tid), json={"values": {k["Название"]: "Роутер", k["Количество"]: 3}}, headers=h)
    ).json()
    same = await client.patch(
        f"{_rows(tid)}/{row['id']}", json={"values": {k["Название"]: "Роутер", k["Количество"]: "3.0"}}, headers=h
    )
    assert same.status_code == 200 and same.json()["updated_at"] == row["updated_at"]  # ничего не менялось


# ── колонки и данные ─────────────────────────────────────────────────────────
async def test_deleted_column_hides_values_but_keeps_data(client, world):
    maker, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _warehouse(client, h)
    k, tid = table["k"], table["id"]
    row = (
        await client.post(_rows(tid), json={"values": {k["Название"]: "Роутер", k["Количество"]: 5}}, headers=h)
    ).json()

    col_id = int(k["Количество"][1:])
    assert (await client.delete(f"{URL}/{tid}/columns/{col_id}", headers=h)).status_code == 200
    shown = (await client.get(_rows(tid), headers=h)).json()["items"][0]["values"]
    assert k["Количество"] not in shown and shown[k["Название"]] == "Роутер"
    assert (
        await client.patch(f"{_rows(tid)}/{row['id']}", json={"values": {k["Количество"]: 1}}, headers=h)
    ).status_code == 422

    again = (await client.post(f"{URL}/{tid}/columns", json=_col("Количество", "number"), headers=h)).json()
    fresh = (await client.get(_rows(tid), headers=h)).json()["items"][0]["values"]
    assert fresh[again["key"]] is None  # новая колонка с тем же именем — пустая
    async with maker() as s:  # старое значение осталось в базе (колонка удалена мягко)
        cells = (
            (await s.execute(select(UserCustomTableCellModel).where(UserCustomTableCellModel.column_id == col_id)))
            .scalars()
            .all()
        )
        assert len(cells) == 1 and cells[0].value_number is not None


async def test_deleted_table_hides_rows(client, world):
    maker, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _warehouse(client, h)
    tid = table["id"]
    row = (await client.post(_rows(tid), json={}, headers=h)).json()
    assert (await client.delete(f"{URL}/{tid}", headers=h)).status_code == 200
    assert (await client.get(_rows(tid), headers=h)).status_code == 404
    assert (await client.post(_rows(tid), json={}, headers=h)).status_code == 404
    assert (await client.delete(f"{_rows(tid)}/{row['id']}", headers=h)).status_code == 404
    async with maker() as s:  # данные остались в базе
        assert len((await s.execute(select(UserCustomTableRowModel))).scalars().all()) == 1


# ── аудит ────────────────────────────────────────────────────────────────────
async def test_row_changes_are_audited(client, world):
    maker, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _warehouse(client, h)
    k, tid = table["k"], table["id"]
    row = (
        await client.post(_rows(tid), json={"values": {k["Название"]: "Роутер", k["Количество"]: 5}}, headers=h)
    ).json()
    await client.patch(f"{_rows(tid)}/{row['id']}", json={"values": {k["Количество"]: 4}}, headers=h)
    await client.delete(f"{_rows(tid)}/{row['id']}", headers=h)

    async with maker() as s:
        logs = (await s.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
    rows_log = [r.action.value for r in logs if r.entity_type == "user_custom_table_rows"]
    cells_log = [r.action.value for r in logs if r.entity_type == "user_custom_table_cells"]
    assert rows_log == ["create", "delete"]  # правка ячеек видна в журнале ячеек, строка меняется только версией
    assert cells_log == ["create", "create", "update"]
    update = [r for r in logs if r.entity_type == "user_custom_table_cells" and r.action.value == "update"][0]
    assert update.old_values["value_number"] is not None and update.new_values["value_number"] is not None
