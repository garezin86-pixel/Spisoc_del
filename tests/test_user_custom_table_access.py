# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_user_custom_table_access.py
"""Самостоятельные таблицы (Smart Tables, этап 4.5): ограниченный доступ (видимость restricted) и участники.

Главные риски: доступ у тех, кого не добавляли; участник только для чтения, который пишет; участник, который
меняет структуру или список; потеря доступа при смене видимости; утечка между компаниями.
"""

import json

import pytest
from sqlalchemy import select

from src.models.audit import AuditLog
from tests.test_clients import _headers, _user, world  # noqa: F401  (world — фикстура)

URL = "/api/user-custom-tables"
TABLES = "/api/tables"


@pytest.fixture
async def people(world):
    """К компании A добавляется третий обычный пользователь: owner — владелец, other — участник, third — посторонний."""
    maker, ids, logins = world
    async with maker() as s:
        third = _user("third", ids["a"])
        s.add(third)
        await s.commit()
        ids = {**ids, "third": third.id}
        logins = {**logins, "third": third.login}
    return maker, ids, logins


async def _table(client, h, visibility="restricted", name="Склад") -> dict:
    resp = await client.post(
        URL,
        json={"name": name, "visibility": visibility, "columns": [{"name": "Название", "data_type": "text"}]},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    table = resp.json()
    table["col"] = table["columns"][0]["key"]
    return table


async def _members(client, h, table, *members) -> list:
    resp = await client.put(f"{URL}/{table['id']}/members", json={"members": list(members)}, headers=h)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rows(table_id: int) -> str:
    return f"{URL}/{table_id}/rows"


# ── кто видит ────────────────────────────────────────────────────────────────
async def test_restricted_table_visible_to_members_only(client, people):
    _, ids, logins = people
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    third_h = await _headers(client, logins, "third")
    table = await _table(client, owner_h)
    tid = table["id"]
    assert (await _members(client, owner_h, table, {"user_id": ids["other"]})) == [
        {"user_id": ids["other"], "username": "other", "can_edit": True}
    ]

    # участник видит таблицу везде: список, карточка, источники, строки
    assert [t["name"] for t in (await client.get(URL, headers=other_h)).json()] == ["Склад"]
    assert (await client.get(f"{URL}/{tid}", headers=other_h)).status_code == 200
    assert f"uct_{tid}" in {s["key"] for s in (await client.get(TABLES, headers=other_h)).json()}
    assert (await client.get(f"{TABLES}/uct_{tid}/meta", headers=other_h)).status_code == 200
    assert (await client.get(_rows(tid), headers=other_h)).status_code == 200

    # посторонний не видит ничего, таблица неотличима от несуществующей
    assert (await client.get(URL, headers=third_h)).json() == []
    assert (await client.get(f"{URL}/{tid}", headers=third_h)).status_code == 404
    assert f"uct_{tid}" not in {s["key"] for s in (await client.get(TABLES, headers=third_h)).json()}
    for path in (f"{TABLES}/uct_{tid}/meta", f"{TABLES}/uct_{tid}/rows", _rows(tid), f"{URL}/{tid}/members"):
        assert (await client.get(path, headers=third_h)).status_code == 404, path
    assert (await client.post(_rows(tid), json={}, headers=third_h)).status_code == 404

    # admin и manager видят и управляют всегда, без членства
    for who in ("a_manager", "a_admin"):
        h = await _headers(client, logins, who)
        assert (await client.get(f"{URL}/{tid}", headers=h)).json()["can_manage"] is True
        assert f"uct_{tid}" in {s["key"] for s in (await client.get(TABLES, headers=h)).json()}


async def test_access_flags_in_list_and_card(client, people):
    _, ids, logins = people
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    readonly = await _table(client, owner_h, name="Только чтение")
    editable = await _table(client, owner_h, name="С правкой")
    shared = await _table(client, owner_h, visibility="shared", name="Общая")
    await _members(client, owner_h, readonly, {"user_id": ids["other"], "can_edit": False})
    await _members(client, owner_h, editable, {"user_id": ids["other"], "can_edit": True})

    by_name = {t["name"]: t for t in (await client.get(URL, headers=other_h)).json()}
    assert (by_name["Только чтение"]["can_edit_rows"], by_name["Только чтение"]["can_manage"]) == (False, False)
    assert (by_name["С правкой"]["can_edit_rows"], by_name["С правкой"]["can_manage"]) == (True, False)
    assert (by_name["Общая"]["can_edit_rows"], by_name["Общая"]["can_manage"]) == (True, False)
    card = (await client.get(f"{URL}/{readonly['id']}", headers=other_h)).json()
    assert (card["can_edit_rows"], card["can_manage"]) == (False, False)
    own = {t["name"]: t for t in (await client.get(URL, headers=owner_h)).json()}
    assert own["Только чтение"]["can_manage"] is True and own["Только чтение"]["can_edit_rows"] is True
    assert shared["id"]


# ── права участников ─────────────────────────────────────────────────────────
async def test_read_only_member_cannot_write_rows(client, people):
    _, ids, logins = people
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    table = await _table(client, owner_h)
    tid, col = table["id"], table["col"]
    await _members(client, owner_h, table, {"user_id": ids["other"], "can_edit": False})
    row = (await client.post(_rows(tid), json={"values": {col: "Роутер"}}, headers=owner_h)).json()

    # читать можно: список строк и общий движок
    assert (await client.get(_rows(tid), headers=other_h)).json()["total"] == 1
    body = (await client.get(f"{TABLES}/uct_{tid}/rows", headers=other_h)).json()
    assert body["items"][0][col] == "Роутер"
    # писать нельзя
    assert (await client.post(_rows(tid), json={"values": {col: "X"}}, headers=other_h)).status_code == 403
    url = f"{_rows(tid)}/{row['id']}"
    assert (await client.patch(url, json={"values": {col: "X"}}, headers=other_h)).status_code == 403
    assert (await client.delete(url, headers=other_h)).status_code == 403
    assert (await client.get(_rows(tid), headers=owner_h)).json()["items"][0]["values"][col] == "Роутер"  # цело

    # дали право на правку — теперь можно
    await _members(client, owner_h, table, {"user_id": ids["other"], "can_edit": True})
    assert (await client.patch(url, json={"values": {col: "Новое"}}, headers=other_h)).status_code == 200
    assert (await client.post(_rows(tid), json={"values": {col: "Ещё"}}, headers=other_h)).status_code == 201
    assert (await client.delete(url, headers=other_h)).status_code == 200


async def test_editing_member_cannot_change_structure_or_members(client, people):
    _, ids, logins = people
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    table = await _table(client, owner_h)
    tid = table["id"]
    await _members(client, owner_h, table, {"user_id": ids["other"], "can_edit": True})
    col_id = table["columns"][0]["id"]

    assert (await client.post(_rows(tid), json={}, headers=other_h)).status_code == 201
    assert (await client.patch(f"{URL}/{tid}", json={"name": "X"}, headers=other_h)).status_code == 403
    assert (await client.delete(f"{URL}/{tid}", headers=other_h)).status_code == 403
    new_column = {"name": "Новая", "data_type": "text"}
    assert (await client.post(f"{URL}/{tid}/columns", json=new_column, headers=other_h)).status_code == 403
    assert (await client.delete(f"{URL}/{tid}/columns/{col_id}", headers=other_h)).status_code == 403
    assert (await client.get(f"{URL}/{tid}/members", headers=other_h)).status_code == 403
    grab = await client.put(f"{URL}/{tid}/members", json={"members": [{"user_id": ids["third"]}]}, headers=other_h)
    assert grab.status_code == 403  # участник не может расширить доступ
    assert (await client.patch(f"{URL}/{tid}", json={"visibility": "shared"}, headers=other_h)).status_code == 403


# ── управление списком ───────────────────────────────────────────────────────
async def test_set_members_replaces_list_and_restores(client, people):
    maker, ids, logins = people
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    third_h = await _headers(client, logins, "third")
    table = await _table(client, owner_h)
    tid = table["id"]

    both = await _members(
        client, owner_h, table, {"user_id": ids["other"]}, {"user_id": ids["third"], "can_edit": False}
    )
    assert {(m["username"], m["can_edit"]) for m in both} == {("other", True), ("third", False)}
    assert (await client.get(f"{URL}/{tid}", headers=third_h)).status_code == 200

    only_other = await _members(client, owner_h, table, {"user_id": ids["other"]})  # third убран из списка
    assert [m["username"] for m in only_other] == ["other"]
    assert (await client.get(f"{URL}/{tid}", headers=third_h)).status_code == 404  # доступ пропал сразу
    assert (await client.get(f"{URL}/{tid}", headers=other_h)).status_code == 200

    back = await _members(client, owner_h, table, {"user_id": ids["third"], "can_edit": True})  # вернули третьего
    assert [(m["username"], m["can_edit"]) for m in back] == [("third", True)]
    assert (await client.get(f"{URL}/{tid}", headers=third_h)).status_code == 200
    assert (await client.get(f"{URL}/{tid}", headers=other_h)).status_code == 404

    assert (await _members(client, owner_h, table)) == []  # пустой список — доступ только у владельца и менеджеров
    assert (await client.get(f"{URL}/{tid}", headers=third_h)).status_code == 404

    async with maker() as s:
        actions = [
            r.action.value
            for r in (await s.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
            if r.entity_type == "user_custom_table_members"
        ]
    assert actions[:2] == ["create", "create"]  # первый список
    assert "delete" in actions and "restore" in actions  # убрали и вернули — всё в аудите
    assert actions.count("update") >= 1  # смена права на правку


async def test_set_members_validation(client, people):
    _, ids, logins = people
    owner_h = await _headers(client, logins, "owner")
    table = await _table(client, owner_h)
    url = f"{URL}/{table['id']}/members"

    async def code(members) -> int:
        return (await client.put(url, json={"members": members}, headers=owner_h)).status_code

    assert await code([{"user_id": 99999}]) == 422  # такого пользователя нет
    assert await code([{"user_id": ids["b_admin"]}]) == 422  # пользователь другой компании
    assert await code([{"user_id": ids["other"]}, {"user_id": ids["other"]}]) == 422  # дважды
    assert await code([{"user_id": 0}]) == 422
    assert await code([{"user_id": ids["other"], "can_edit": "да"}]) == 422
    assert await code([{"user_id": i} for i in range(1, 102)]) == 422  # больше 100
    assert (await client.put(url, json={}, headers=owner_h)).status_code == 200  # без списка — пусто
    assert await code([{"user_id": ids["owner"]}]) == 200  # владелец в списке — безвредно
    assert (await client.put(f"{URL}/99999/members", json={"members": []}, headers=owner_h)).status_code == 404
    assert (await client.get(url)).status_code in (401, 403)


# ── видимость ────────────────────────────────────────────────────────────────
async def test_visibility_switch_keeps_members(client, people):
    _, ids, logins = people
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    third_h = await _headers(client, logins, "third")
    table = await _table(client, owner_h)
    tid = table["id"]
    await _members(client, owner_h, table, {"user_id": ids["other"]})

    def patch(visibility):
        return client.patch(f"{URL}/{tid}", json={"visibility": visibility}, headers=owner_h)

    assert (await patch("private")).status_code == 200  # личная: участники доступа не имеют
    assert (await client.get(f"{URL}/{tid}", headers=other_h)).status_code == 404
    assert (await patch("shared")).status_code == 200  # общая: видят все
    assert (await client.get(f"{URL}/{tid}", headers=third_h)).status_code == 200
    assert (await patch("restricted")).status_code == 200  # снова ограниченная: список участников сохранился
    assert (await client.get(f"{URL}/{tid}", headers=other_h)).status_code == 200
    assert (await client.get(f"{URL}/{tid}", headers=third_h)).status_code == 404
    assert [m["username"] for m in (await client.get(f"{URL}/{tid}/members", headers=owner_h)).json()] == ["other"]
    assert (await patch("public")).status_code == 422


async def test_members_of_private_table_get_no_access(client, people):
    _, ids, logins = people
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    table = await _table(client, owner_h, visibility="private")
    await _members(client, owner_h, table, {"user_id": ids["other"]})  # список можно подготовить заранее
    assert (await client.get(f"{URL}/{table['id']}", headers=other_h)).status_code == 404
    assert (await client.get(URL, headers=other_h)).json() == []


async def test_restricted_table_after_owner_left(client, people):
    maker, ids, logins = people
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    manager_h = await _headers(client, logins, "a_manager")
    table = await _table(client, owner_h)
    tid = table["id"]
    await _members(client, owner_h, table, {"user_id": ids["other"]})
    from src.models.user_custom_table import UserCustomTableModel

    async with maker() as s:  # владелец уволен
        row = await s.get(UserCustomTableModel, tid)
        row.owner_id = None
        await s.commit()
    assert (await client.get(f"{URL}/{tid}", headers=other_h)).status_code == 200  # участники не потеряли доступ
    assert (await client.get(f"{URL}/{tid}", headers=owner_h)).status_code == 404  # бывший владелец — уже нет
    new_owner = await client.patch(f"{URL}/{tid}", json={"owner_id": ids["third"]}, headers=manager_h)
    assert new_owner.status_code == 200


# ── общий движок и изоляция ──────────────────────────────────────────────────
async def test_removed_member_loses_query_access_immediately(client, people):
    _, ids, logins = people
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    table = await _table(client, owner_h)
    tid, col = table["id"], table["col"]
    await client.post(_rows(tid), json={"values": {col: "Роутер"}}, headers=owner_h)
    await _members(client, owner_h, table, {"user_id": ids["other"]})
    params = {"filters": json.dumps([{"field": col, "op": "contains", "value": "Роутер"}])}
    found = await client.get(f"{TABLES}/uct_{tid}/rows", params=params, headers=other_h)
    assert found.status_code == 200 and found.json()["total"] == 1  # участник ищет в таблице
    await _members(client, owner_h, table)
    assert (await client.get(f"{TABLES}/uct_{tid}/rows", headers=other_h)).status_code == 404
    assert f"uct_{tid}" not in {s["key"] for s in (await client.get(TABLES, headers=other_h)).json()}


async def test_members_isolation_between_companies(client, people):
    _, ids, logins = people
    owner_h = await _headers(client, logins, "owner")
    hb = await _headers(client, logins, "b_admin")
    table = await _table(client, owner_h)
    await _members(client, owner_h, table, {"user_id": ids["other"]})
    url = f"{URL}/{table['id']}/members"
    assert (await client.get(url, headers=hb)).status_code == 404
    assert (await client.put(url, json={"members": []}, headers=hb)).status_code == 404
    assert [m["username"] for m in (await client.get(url, headers=owner_h)).json()] == ["other"]  # у A всё цело
