# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_user_custom_tables.py
"""Самостоятельные таблицы (Smart Tables, этап 4.1): таблицы и колонки.

Главные риски: чужие личные таблицы, правка таблицы без прав, потеря данных при смене/уходе владельца,
утечка между компаниями, смена типа колонки (потеряла бы смысл введённые значения).
"""

from sqlalchemy import select

from src.models.audit import AuditLog
from src.models.user_custom_table import UserCustomTableColumnModel, UserCustomTableModel
from src.services import user_custom_table_service
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)

URL = "/api/user-custom-tables"


async def _table(client, h, name="Склад", **extra) -> dict:
    resp = await client.post(URL, json={"name": name} | extra, headers=h)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _col(name: str, data_type: str = "text", **extra) -> dict:
    return {"name": name, "data_type": data_type} | extra


# ── создание и чтение ────────────────────────────────────────────────────────
async def test_any_user_creates_table_with_columns(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "other")  # обычный пользователь тоже может создать таблицу
    table = await _table(
        client,
        h,
        "  Оборудование  ",
        description="  Что есть на складе  ",
        icon="📦",
        columns=[
            _col("Название"),
            _col("Количество", "number"),
            _col("Поступило", "date"),
            _col("На складе", "boolean"),
            _col("Состояние", "select", options=["Новый", " БУ ", "Сломан"]),
        ],
    )
    assert table["name"] == "Оборудование" and table["description"] == "Что есть на складе" and table["icon"] == "📦"
    assert table["visibility"] == "shared" and table["owner_id"] == ids["other"]
    cols = table["columns"]
    assert [c["name"] for c in cols] == ["Название", "Количество", "Поступило", "На складе", "Состояние"]
    assert [c["position"] for c in cols] == [0, 1, 2, 3, 4]
    assert [c["key"] for c in cols] == [f"c{c['id']}" for c in cols]
    assert cols[4]["options"] == ["Новый", "БУ", "Сломан"] and cols[0]["options"] is None

    got = (await client.get(f"{URL}/{table['id']}", headers=h)).json()
    assert got == table
    listing = (await client.get(URL, headers=h)).json()
    assert [(t["name"], t["columns_count"]) for t in listing] == [("Оборудование", 5)]
    empty = await _table(client, h, "Пустая")  # можно без колонок и добавить позже
    assert empty["columns"] == [] and empty["description"] is None


async def test_create_validation(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")

    async def code(**payload) -> int:
        return (await client.post(URL, json={"name": "Т"} | payload, headers=h)).status_code

    assert await code(name="   ") == 422
    assert await code(name="x" * 101) == 422
    assert await code(description="x" * 501) == 422
    assert await code(icon="x" * 17) == 422
    assert await code(visibility="public") == 422
    assert await code(columns=[_col("A"), _col("a")]) == 422  # повтор названия без учёта регистра
    assert await code(columns=[_col("A", "json")]) == 422
    assert await code(columns=[_col("A", "select")]) == 422  # у списка нужны значения
    assert await code(columns=[_col("A", "text", options=["x"])]) == 422
    assert await code(columns=[_col("   ")]) == 422
    assert await code(columns=[_col(f"К{i}") for i in range(51)]) == 422
    assert await code(columns=[_col(f"К{i}") for i in range(50)]) == 201
    assert (await client.post(URL, json={}, headers=h)).status_code == 422
    assert (await client.get(URL)).status_code in (401, 403)


async def test_table_limit(client, world, monkeypatch):
    _, _, logins = world
    monkeypatch.setattr(user_custom_table_service, "MAX_TABLES_PER_WORKSPACE", 2)
    h = await _headers(client, logins, "owner")
    await _table(client, h, "Раз")
    await _table(client, h, "Два")
    assert (await client.post(URL, json={"name": "Три"}, headers=h)).status_code == 409


# ── видимость и права ────────────────────────────────────────────────────────
async def test_private_table_visibility(client, world):
    _, _, logins = world
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    private = await _table(client, owner_h, "Личная", visibility="private")
    shared = await _table(client, owner_h, "Общая")

    assert [t["name"] for t in (await client.get(URL, headers=owner_h)).json()] == ["Личная", "Общая"]
    assert [t["name"] for t in (await client.get(URL, headers=other_h)).json()] == ["Общая"]
    assert (await client.get(f"{URL}/{private['id']}", headers=other_h)).status_code == 404  # существование не выдаётся
    assert (await client.patch(f"{URL}/{private['id']}", json={"name": "X"}, headers=other_h)).status_code == 404
    assert (await client.post(f"{URL}/{private['id']}/columns", json=_col("A"), headers=other_h)).status_code == 404
    for who in ("a_manager", "a_admin"):  # admin и manager видят и личные
        h = await _headers(client, logins, who)
        assert [t["name"] for t in (await client.get(URL, headers=h)).json()] == ["Личная", "Общая"]
        assert (await client.get(f"{URL}/{private['id']}", headers=h)).status_code == 200

    shared_now = await client.patch(f"{URL}/{private['id']}", json={"visibility": "shared"}, headers=owner_h)
    assert shared_now.json()["visibility"] == "shared"
    assert (await client.get(f"{URL}/{private['id']}", headers=other_h)).status_code == 200
    assert shared["id"]


async def test_only_owner_and_managers_change_table(client, world):
    _, _, logins = world
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    table = await _table(client, owner_h, "Общая", columns=[_col("A")])
    col_id = table["columns"][0]["id"]
    tid = table["id"]

    assert (await client.get(f"{URL}/{tid}", headers=other_h)).status_code == 200  # читать можно
    assert (await client.patch(f"{URL}/{tid}", json={"name": "X"}, headers=other_h)).status_code == 403
    assert (await client.delete(f"{URL}/{tid}", headers=other_h)).status_code == 403
    assert (await client.post(f"{URL}/{tid}/columns", json=_col("B"), headers=other_h)).status_code == 403
    assert (await client.patch(f"{URL}/{tid}/columns/{col_id}", json={"name": "X"}, headers=other_h)).status_code == 403
    assert (await client.delete(f"{URL}/{tid}/columns/{col_id}", headers=other_h)).status_code == 403

    assert (await client.patch(f"{URL}/{tid}", json={"name": "От владельца"}, headers=owner_h)).status_code == 200
    manager_h = await _headers(client, logins, "a_manager")
    assert (await client.patch(f"{URL}/{tid}", json={"name": "От менеджера"}, headers=manager_h)).status_code == 200
    renamed = (await client.get(f"{URL}/{tid}", headers=other_h)).json()
    assert renamed["name"] == "От менеджера"


async def test_update_table_fields(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _table(client, h, "Старое", description="Описание", icon="📦")
    url = f"{URL}/{table['id']}"
    patched = await client.patch(url, json={"name": "  Новое  ", "description": None, "icon": ""}, headers=h)
    body = patched.json()
    assert body["name"] == "Новое" and body["description"] is None and body["icon"] is None  # null и «» очищают
    assert (await client.patch(url, json={"name": None}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"name": " "}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"visibility": None}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"visibility": "x"}, headers=h)).status_code == 422
    assert (await client.patch(url, json={}, headers=h)).status_code == 200  # пустой PATCH ничего не меняет


async def test_owner_change_and_departed_owner(client, world):
    maker, ids, logins = world
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    manager_h = await _headers(client, logins, "a_manager")
    table = await _table(client, owner_h, "Личная", visibility="private")
    url = f"{URL}/{table['id']}"

    assert (await client.patch(url, json={"owner_id": ids["other"]}, headers=owner_h)).status_code == 403
    assert (await client.patch(url, json={"owner_id": 99999}, headers=manager_h)).status_code == 404
    assert (
        await client.patch(url, json={"owner_id": ids["b_admin"]}, headers=manager_h)
    ).status_code == 404  # чужая компания
    assert (await client.patch(url, json={"owner_id": None}, headers=manager_h)).status_code == 422

    moved = await client.patch(url, json={"owner_id": ids["other"]}, headers=manager_h)
    assert moved.status_code == 200 and moved.json()["owner_id"] == ids["other"]
    assert (await client.get(url, headers=other_h)).status_code == 200  # новый владелец видит личную таблицу
    assert (await client.get(url, headers=owner_h)).status_code == 404  # бывший — уже нет
    assert (await client.patch(url, json={"name": "X"}, headers=other_h)).status_code == 200

    async with maker() as s:  # владелец уволен: users.owner_id -> NULL, таблица осталась
        row = await s.get(UserCustomTableModel, table["id"])
        row.owner_id = None
        await s.commit()
    assert (await client.get(url, headers=other_h)).status_code == 404
    assert (await client.get(url, headers=manager_h)).status_code == 200  # данные не потеряны
    assert (await client.patch(url, json={"owner_id": ids["owner"]}, headers=manager_h)).status_code == 200
    assert (await client.get(url, headers=owner_h)).status_code == 200


# ── колонки ──────────────────────────────────────────────────────────────────
async def test_column_lifecycle(client, world, monkeypatch):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _table(client, h, "Склад")
    url = f"{URL}/{table['id']}/columns"

    a = (await client.post(url, json=_col("  Название  "), headers=h)).json()
    b = (await client.post(url, json=_col("Состояние", "select", options=["Новый", "БУ"]), headers=h)).json()
    assert a["name"] == "Название" and a["position"] == 0 and b["position"] == 1 and a["key"] == f"c{a['id']}"
    assert (await client.post(url, json=_col("название"), headers=h)).status_code == 409  # регистр не важен

    renamed = await client.patch(f"{url}/{a['id']}", json={"name": "Модель"}, headers=h)
    assert renamed.json()["name"] == "Модель" and renamed.json()["key"] == a["key"]  # ключ не меняется
    assert (await client.patch(f"{url}/{a['id']}", json={"name": "состояние"}, headers=h)).status_code == 409
    assert (
        await client.patch(f"{url}/{a['id']}", json={"name": "Модель"}, headers=h)
    ).status_code == 200  # себя не считает
    retyped = await client.patch(f"{url}/{a['id']}", json={"data_type": "number"}, headers=h)
    assert retyped.json()["data_type"] == "text"  # тип после создания не меняется
    assert (await client.patch(f"{url}/{a['id']}", json={"options": ["x"]}, headers=h)).status_code == 422
    assert (await client.patch(f"{url}/{a['id']}", json={"name": None}, headers=h)).status_code == 422
    options = await client.patch(f"{url}/{b['id']}", json={"options": ["Новый", "БУ", "Сломан"]}, headers=h)
    assert options.json()["options"] == ["Новый", "БУ", "Сломан"]
    assert (await client.patch(f"{url}/{b['id']}", json={"options": ["A", "a"]}, headers=h)).status_code == 422

    await client.patch(f"{url}/{a['id']}", json={"position": 5}, headers=h)  # порядок задаёт интерфейс
    names = [c["name"] for c in (await client.get(f"{URL}/{table['id']}", headers=h)).json()["columns"]]
    assert names == ["Состояние", "Модель"]

    assert (await client.delete(f"{url}/{b['id']}", headers=h)).status_code == 200
    names = [c["name"] for c in (await client.get(f"{URL}/{table['id']}", headers=h)).json()["columns"]]
    assert names == ["Модель"]
    assert (await client.delete(f"{url}/{b['id']}", headers=h)).status_code == 404
    assert (await client.patch(f"{url}/{b['id']}", json={"name": "X"}, headers=h)).status_code == 404
    again = (await client.post(url, json=_col("Состояние", "number"), headers=h)).json()
    assert again["id"] != b["id"] and again["data_type"] == "number"  # имя удалённой колонки свободно

    monkeypatch.setattr(user_custom_table_service, "MAX_COLUMNS_PER_TABLE", 2)
    assert (await client.post(url, json=_col("Лишняя"), headers=h)).status_code == 409


async def test_column_belongs_to_table_in_url(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    t1 = await _table(client, h, "Раз", columns=[_col("A")])
    t2 = await _table(client, h, "Два")
    col_id = t1["columns"][0]["id"]
    assert (await client.patch(f"{URL}/{t2['id']}/columns/{col_id}", json={"name": "X"}, headers=h)).status_code == 404
    assert (await client.delete(f"{URL}/{t2['id']}/columns/{col_id}", headers=h)).status_code == 404
    assert (await client.get(f"{URL}/99999", headers=h)).status_code == 404


# ── удаление ─────────────────────────────────────────────────────────────────
async def test_soft_delete_table(client, world):
    maker, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _table(client, h, "Склад", columns=[_col("A")])
    url = f"{URL}/{table['id']}"
    assert (await client.delete(url, headers=h)).status_code == 200
    assert (await client.get(url, headers=h)).status_code == 404
    assert (await client.get(URL, headers=h)).json() == []
    assert (await client.delete(url, headers=h)).status_code == 404
    assert (await client.post(f"{url}/columns", json=_col("B"), headers=h)).status_code == 404
    async with maker() as s:  # данные остались в базе
        row = await s.get(UserCustomTableModel, table["id"])
        assert row is not None and row.deleted_at is not None
        columns = (await s.execute(select(UserCustomTableColumnModel))).scalars().all()
        assert len(columns) == 1


# ── изоляция и аудит ─────────────────────────────────────────────────────────
async def test_isolation_between_companies(client, world):
    _, _, logins = world
    ha = await _headers(client, logins, "a_manager")
    table = await _table(client, ha, "Склад A", columns=[_col("A")])
    url = f"{URL}/{table['id']}"
    col_id = table["columns"][0]["id"]

    hb = await _headers(client, logins, "b_admin")
    assert (await client.get(URL, headers=hb)).json() == []
    assert (await client.get(url, headers=hb)).status_code == 404
    assert (await client.patch(url, json={"name": "X"}, headers=hb)).status_code == 404
    assert (await client.delete(url, headers=hb)).status_code == 404
    assert (await client.post(f"{url}/columns", json=_col("B"), headers=hb)).status_code == 404
    assert (await client.patch(f"{url}/columns/{col_id}", json={"name": "X"}, headers=hb)).status_code == 404
    own = await _table(client, hb, "Склад B")  # то же имя в другой компании — отдельная таблица
    assert own["id"] != table["id"]
    assert [t["name"] for t in (await client.get(URL, headers=ha)).json()] == ["Склад A"]


async def test_changes_are_audited(client, world):
    maker, _, logins = world
    h = await _headers(client, logins, "a_manager")
    table = await _table(client, h, "Склад", columns=[_col("A")])
    await client.patch(f"{URL}/{table['id']}", json={"name": "Склад 2"}, headers=h)
    col = (await client.post(f"{URL}/{table['id']}/columns", json=_col("B"), headers=h)).json()
    await client.patch(f"{URL}/{table['id']}/columns/{col['id']}", json={"name": "B2"}, headers=h)
    await client.delete(f"{URL}/{table['id']}/columns/{col['id']}", headers=h)
    await client.delete(f"{URL}/{table['id']}", headers=h)

    async with maker() as s:
        rows = (await s.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
    tables = [r.action.value for r in rows if r.entity_type == "user_custom_tables"]
    columns = [r.action.value for r in rows if r.entity_type == "user_custom_table_columns"]
    assert tables == ["create", "update", "delete"]
    assert columns == ["create", "create", "update", "delete"]  # начальная колонка, B, переименование, удаление
