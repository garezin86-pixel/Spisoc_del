# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_user_table_import.py
"""Импорт CSV/XLSX в самостоятельные таблицы (Smart Tables, шаг 4.6).

Главные риски: потеря данных при разборе (запятая в числах, ведущие нули, даты), запись без права на правку,
частичный импорт при ошибке, превышение лимитов, утечка между компаниями.
"""

import io
import json
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from src.models.user_custom_table import UserCustomTableModel
from src.services import client_import_service
from src.services import user_custom_table_row_service as row_limits
from src.services import user_custom_table_service as table_limits
from src.services import user_table_import_service as import_limits
from src.services.user_table_import_service import (
    infer_type,
    parse_bool,
    parse_number,
    parse_select,
)
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)

URL = "/api/user-custom-tables"
TABLES = "/api/tables"
CSV = "text/csv"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _csv(*lines: str, sep: str = ";") -> bytes:
    return ("\n".join(sep.join(line.split("|")) for line in lines) + "\n").encode("utf-8-sig")


def _xlsx(*rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(list(row))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _file(content: bytes, filename="data.csv", mime=CSV) -> dict:
    return {"file": (filename, content, mime)}


def _col(name: str, data_type: str = "text", **extra) -> dict:
    return {"name": name, "data_type": data_type} | extra


async def _stock(client, h, **extra) -> dict:
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
                _col("Клиент", "client"),
            ],
        }
        | extra,
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    table = resp.json()
    table["k"] = {c["name"]: c["key"] for c in table["columns"]}
    return table


async def _import(client, h, table, content, mapping, dry_run=False, **file_kwargs):
    return await client.post(
        f"{URL}/{table['id']}/import",
        files=_file(content, **file_kwargs),
        data={"mapping": json.dumps(mapping), "dry_run": "true" if dry_run else "false"},
        headers=h,
    )


async def _rows(client, h, table_id) -> list[dict]:
    resp = await client.get(f"{URL}/{table_id}/rows", params={"size": 200}, headers=h)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


# ── разбор значений ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12,5", Decimal("12.5")),
        ("12.5", Decimal("12.5")),
        ("1 234,50", Decimal("1234.5")),
        ("1\u00a0234,50", Decimal("1234.5")),
        ("1.234,50", Decimal("1234.5")),
        ("1,234.50", Decimal("1234.5")),
        ("1,234,567", Decimal("1234567")),
        ("-7", Decimal("-7")),
        (15, Decimal("15")),
        (0.1 + 0.2, Decimal("0.3")),  # шум чисел с плавающей точкой из Excel не считается потерей
        ("", None),
        (None, None),
    ],
)
def test_parse_number(raw, expected):
    value, warning = parse_number(raw)
    assert value == expected and warning is None


@pytest.mark.parametrize("raw", ["abc", "12abc", True, "1e999999", 10**14, "NaN", "--5"])
def test_parse_number_rejects(raw):
    value, warning = parse_number(raw)
    assert value is None and warning


def test_parse_number_warns_when_rounding_real_digits():
    value, warning = parse_number("1,234567")
    assert value == Decimal("1.2346") and "округлено" in warning


@pytest.mark.parametrize("raw", ["да", "Да", " YES ", "true", "+", 1, 1.0, True])
def test_parse_bool_true(raw):
    assert parse_bool(raw) == (True, None)


@pytest.mark.parametrize("raw", ["нет", "No", "false", "-", 0, False])
def test_parse_bool_false(raw):
    assert parse_bool(raw) == (False, None)


def test_parse_bool_unknown_and_empty():
    assert parse_bool("возможно")[0] is None and parse_bool("возможно")[1]
    assert parse_bool("") == (None, None) and parse_bool(None) == (None, None)


def test_parse_select_ignores_case_and_rejects_unknown():
    assert parse_select(" бу ", ["Новый", "БУ"]) == ("БУ", None)
    value, warning = parse_select("Неизвестно", ["Новый", "БУ"])
    assert value is None and "нет в списке" in warning


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["15", "3,5", 40], "number"),
        (["21.11.2026", "01.12.2026"], "date"),
        ([date(2026, 1, 1), date(2026, 2, 1)], "date"),
        ([True, False], "boolean"),
        (["да", "нет", "да"], "boolean"),
        (["0", "1", "1"], "number"),  # только нули и единицы — это числа, а не да/нет
        (["0123456", "0654321"], "text"),  # ведущий ноль: числом был бы потерян
        (["380987654321", "380991112233"], "text"),  # телефон
        (["123456", "654321"], "number"),  # короткие числа — числа
        (["15", "много"], "text"),  # не все значения числа — без потерь остаётся текст
        (["", None], "text"),
        ([], "text"),
    ],
)
def test_infer_type(values, expected):
    assert infer_type(values) == expected


# ── колонки файла ────────────────────────────────────────────────────────────
async def test_describe_file_and_table(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "other")  # любой пользователь
    content = _csv("Название|Количество|Дата|ЛС", "Роутер|15|21.11.2026|0123456", "ONU|3,5|22.11.2026|0654321")
    resp = await client.post(f"{URL}/from-file/columns", files=_file(content), headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 2 and body["table_columns"] is None
    assert [(c["header"], c["suggested_type"]) for c in body["columns"]] == [
        ("Название", "text"),
        ("Количество", "number"),
        ("Дата", "date"),
        ("ЛС", "text"),
    ]
    assert body["columns"][0]["samples"] == ["Роутер", "ONU"]

    assert (
        await client.post(f"{URL}/from-file/columns", files=_file(b"x", "a.txt", "text/plain"), headers=h)
    ).status_code == 422
    assert (await client.post(f"{URL}/from-file/columns", files=_file(b"", "a.csv"), headers=h)).status_code == 422

    owner_h = await _headers(client, logins, "owner")
    table = await _stock(client, owner_h)
    k = table["k"]
    described = await client.post(f"{URL}/{table['id']}/import/columns", files=_file(content), headers=owner_h)
    data = described.json()
    assert {c["name"]: c["importable"] for c in data["table_columns"]} == {
        "Название": True,
        "Количество": True,
        "Поступило": True,
        "На складе": True,
        "Состояние": True,
        "Клиент": False,  # связь из файла не заполняется
    }
    assert data["suggested_mapping"] == {k["Название"]: 0, k["Количество"]: 1}  # по названиям колонок


# ── импорт в таблицу ─────────────────────────────────────────────────────────
async def test_import_into_table_with_preview_and_types(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "other")  # обычный пользователь, общая таблица
    table = await _stock(client, h)
    k = table["k"]
    content = _csv(
        "Название|Кол-во|Дата|Есть|Статус",
        "Роутер X|1 234,50|21.11.2026|да|новый",
        "ONU Y|3|2026-12-01|нет|БУ",
        "Кабель|abc|вчера|возможно|неизвестно",
        "|abc|вчера|возможно|неизвестно",  # после разбора ни одного значения: строка пропускается
        "|||",  # совсем пустая строка отбрасывается ещё при чтении файла
    )
    mapping = {k["Название"]: 0, k["Количество"]: 1, k["Поступило"]: 2, k["На складе"]: 3, k["Состояние"]: 4}

    preview = await _import(client, h, table, content, mapping, dry_run=True)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["dry_run"] is True and body["total_rows"] == 4 and body["created"] == 0 and body["to_create"] == 3
    assert body["preview"][0] == {
        "row": 2,
        "values": {
            "Название": "Роутер X",
            "Количество": 1234.5,
            "Поступило": "2026-11-21",
            "На складе": True,
            "Состояние": "Новый",
        },
    }
    messages = [(w["row"], w["message"]) for w in body["warnings"]]
    assert (4, "«Количество»: число «abc» не распознано, оставлено пустым") in messages
    assert any(row == 4 and "«Поступило»" in msg for row, msg in messages)
    assert any(row == 4 and "«На складе»" in msg for row, msg in messages)
    assert any(row == 4 and "«Состояние»" in msg and "нет в списке" in msg for row, msg in messages)
    assert body["errors"] == [{"row": 5, "message": "в строке не осталось ни одного значения — пропущена"}]
    assert await _rows(client, h, table["id"]) == []  # предпросмотр ничего не создал

    done = await _import(client, h, table, content, mapping)
    assert done.status_code == 200 and done.json()["created"] == 3 and done.json()["dry_run"] is False
    rows = await _rows(client, h, table["id"])
    assert [r["values"][k["Название"]] for r in rows] == ["Роутер X", "ONU Y", "Кабель"]
    assert rows[0]["values"][k["Количество"]] == 1234.5 and rows[0]["values"][k["Состояние"]] == "Новый"
    assert rows[1]["values"][k["Поступило"]] == "2026-12-01" and rows[1]["values"][k["На складе"]] is False
    assert rows[2]["values"][k["Количество"]] is None and rows[2]["values"][k["Состояние"]] is None  # неверное — пусто
    assert rows[0]["created_by_id"] is not None

    shown = await client.get(f"{TABLES}/uct_{table['id']}/rows", headers=h)  # в общем движке те же данные
    assert shown.json()["total"] == 3


async def test_import_xlsx_and_partial_mapping(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _stock(client, h)
    k = table["k"]
    content = _xlsx(
        ["Название", "Остаток", "Поступило", "Есть"],
        ["Роутер", 15, date(2026, 11, 21), True],
        ["ONU", 3.5, date(2026, 12, 1), False],
    )
    resp = await _import(
        client, h, table, content, {k["Название"]: 0, k["Количество"]: 1}, filename="s.xlsx", mime=XLSX
    )
    assert resp.status_code == 200 and resp.json()["created"] == 2 and resp.json()["warnings"] == []
    rows = await _rows(client, h, table["id"])
    assert rows[0]["values"][k["Количество"]] == 15.0 and rows[1]["values"][k["Количество"]] == 3.5
    assert rows[0]["values"][k["Поступило"]] is None  # не сопоставленные колонки остались пустыми

    full = await _import(
        client,
        h,
        table,
        content,
        {k["Название"]: 0, k["Поступило"]: 2, k["На складе"]: 3},
        filename="s.xlsx",
        mime=XLSX,
    )
    assert full.json()["created"] == 2
    rows = await _rows(client, h, table["id"])
    assert rows[2]["values"][k["Поступило"]] == "2026-11-21" and rows[2]["values"][k["На складе"]] is True


async def test_import_mapping_validation(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _stock(client, h)
    k = table["k"]
    content = _csv("Название|Количество", "Роутер|1")

    async def code(mapping_raw: str) -> int:
        resp = await client.post(
            f"{URL}/{table['id']}/import", files=_file(content), data={"mapping": mapping_raw}, headers=h
        )
        return resp.status_code

    name, qty = k["Название"], k["Количество"]
    assert await code("не json") == 422
    assert await code("[1, 2]") == 422
    assert await code("{}") == 422  # ничего не выбрано
    assert await code(json.dumps({name: "0"})) == 422  # номер колонки должен быть числом
    assert await code(json.dumps({name: True})) == 422
    assert await code(json.dumps({"c99999": 0})) == 422  # такой колонки в таблице нет
    assert await code(json.dumps({name: 0, qty: 0})) == 422  # одна колонка файла дважды
    assert await code(json.dumps({name: 5})) == 422  # в файле нет такой колонки
    assert await code(json.dumps({name: -1})) == 422
    assert await code(json.dumps({k["Клиент"]: 0})) == 422  # связь из файла не заполняется
    assert await code(json.dumps({name: 0})) == 200
    bad_file = await client.post(
        f"{URL}/{table['id']}/import",
        files=_file(b"x", "a.pdf", "application/pdf"),
        data={"mapping": json.dumps({name: 0})},
        headers=h,
    )
    assert bad_file.status_code == 422
    assert len(await _rows(client, h, table["id"])) == 1  # отклонённые запросы ничего не создали


async def test_import_permissions(client, world):
    _, ids, logins = world
    owner_h = await _headers(client, logins, "owner")
    other_h = await _headers(client, logins, "other")
    content = _csv("Название", "Роутер")

    private = await _stock(client, owner_h, visibility="private")
    mapping = {private["k"]["Название"]: 0}
    assert (await _import(client, other_h, private, content, mapping)).status_code == 404  # чужая личная
    assert (
        await client.post(f"{URL}/{private['id']}/import/columns", files=_file(content), headers=other_h)
    ).status_code == 404

    restricted = await _stock(client, owner_h, visibility="restricted")
    mapping = {restricted["k"]["Название"]: 0}
    put = await client.put(
        f"{URL}/{restricted['id']}/members",
        json={"members": [{"user_id": ids["other"], "can_edit": False}]},
        headers=owner_h,
    )
    assert put.status_code == 200
    assert (await _import(client, other_h, restricted, content, mapping)).status_code == 403  # только чтение
    assert (
        await client.post(f"{URL}/{restricted['id']}/import/columns", files=_file(content), headers=other_h)
    ).status_code == 403
    await client.put(
        f"{URL}/{restricted['id']}/members",
        json={"members": [{"user_id": ids["other"], "can_edit": True}]},
        headers=owner_h,
    )
    assert (await _import(client, other_h, restricted, content, mapping)).status_code == 200  # есть право на правку
    assert (
        await client.post(f"{URL}/{restricted['id']}/import", files=_file(content), data={"mapping": "{}"})
    ).status_code in (
        401,
        403,
    )

    hb = await _headers(client, logins, "b_admin")  # другая компания
    assert (await _import(client, hb, restricted, content, mapping)).status_code == 404


async def test_import_limits(client, world, monkeypatch):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _stock(client, h)
    k = table["k"]
    mapping = {k["Название"]: 0}
    content = _csv("Название", "А", "Б", "В")

    monkeypatch.setattr(client_import_service, "MAX_IMPORT_ROWS", 2)
    assert (await _import(client, h, table, content, mapping)).status_code == 422  # слишком много строк за раз
    monkeypatch.setattr(client_import_service, "MAX_IMPORT_ROWS", 5000)

    monkeypatch.setattr(row_limits, "MAX_ROWS_PER_TABLE", 4)
    assert (await _import(client, h, table, content, mapping)).status_code == 200  # 3 из 4
    over = await _import(client, h, table, content, mapping)
    assert over.status_code == 409  # было бы 6 из 4 — не импортируем ничего
    assert len(await _rows(client, h, table["id"])) == 3
    assert (
        await _import(client, h, table, content, mapping, dry_run=True)
    ).status_code == 409  # предпросмотр честно предупреждает


# ── создание таблицы из файла ────────────────────────────────────────────────
async def test_create_table_from_file_infers_columns(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "other")  # создавать из файла может любой
    content = _csv(
        "Название|Количество|Дата|Есть|ЛС|Название|",
        "Роутер|15|21.11.2026|да|0123456|Первый|x",
        "ONU|3,5|22.11.2026|нет|0654321|Второй|y",
    )
    resp = await client.post(
        f"{URL}/from-file", files=_file(content), data={"name": "  Из файла  ", "visibility": "private"}, headers=h
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 2 and body["dry_run"] is False and body["errors"] == []
    table = body["table"]
    assert table["name"] == "Из файла" and table["visibility"] == "private" and table["owner_id"] == ids["other"]
    assert [(c["name"], c["data_type"]) for c in table["columns"]] == [
        ("Название", "text"),
        ("Количество", "number"),
        ("Дата", "date"),
        ("Есть", "boolean"),
        ("ЛС", "text"),  # ведущий ноль сохранён
        ("Название (2)", "text"),  # повторяющийся заголовок получил номер
        ("Колонка 7", "text"),  # у пустого заголовка — имя по номеру
    ]
    keys = {c["name"]: c["key"] for c in table["columns"]}
    rows = await _rows(client, h, table["id"])
    assert rows[0]["values"][keys["ЛС"]] == "0123456" and rows[1]["values"][keys["Количество"]] == 3.5
    assert rows[0]["values"][keys["Дата"]] == "2026-11-21" and rows[1]["values"][keys["Есть"]] is False
    query = await client.get(f"{TABLES}/uct_{table['id']}/rows", headers=h)  # сразу доступна в общем движке
    assert query.status_code == 200 and query.json()["total"] == 2


async def test_create_table_from_file_with_explicit_columns(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    content = _csv("ЛС|Статус|Сумма|Лишнее", "123456|Новый|10,5|x", "654321|БУ|20|y", "111111|Сломан|abc|z")
    specs = [
        {"index": 0, "name": "Лицевой счёт", "data_type": "text"},  # число из файла остаётся текстом
        {"index": 1, "data_type": "select", "options": ["Новый", "БУ"]},
        {"index": 2, "name": "Сумма", "data_type": "number"},
    ]
    resp = await client.post(
        f"{URL}/from-file", files=_file(content), data={"name": "Счета", "columns": json.dumps(specs)}, headers=h
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    table = body["table"]
    assert [(c["name"], c["data_type"], c["options"]) for c in table["columns"]] == [
        ("Лицевой счёт", "text", None),
        ("Статус", "select", ["Новый", "БУ"]),
        ("Сумма", "number", None),
    ]
    messages = [(w["row"], w["message"]) for w in body["warnings"]]
    assert any(row == 4 and "«Статус»" in msg and "нет в списке" in msg for row, msg in messages)
    assert any(row == 4 and "«Сумма»" in msg for row, msg in messages)
    keys = {c["name"]: c["key"] for c in table["columns"]}
    rows = await _rows(client, h, table["id"])
    assert [r["values"][keys["Лицевой счёт"]] for r in rows] == ["123456", "654321", "111111"]
    assert rows[1]["values"][keys["Сумма"]] == 20.0 and rows[2]["values"][keys["Статус"]] is None


async def test_create_table_from_file_dry_run_and_validation(client, world, monkeypatch):
    maker, _, logins = world
    h = await _headers(client, logins, "owner")
    content = _csv("Название|Количество", "Роутер|15")

    async def post(data: dict, content=content, filename="d.csv"):
        return await client.post(f"{URL}/from-file", files=_file(content, filename), data=data, headers=h)

    preview = await post({"name": "Т", "dry_run": "true"})
    assert preview.status_code == 200 and preview.json()["to_create"] == 1 and preview.json()["table"] is None
    assert preview.json()["created"] == 0
    assert (await client.get(URL, headers=h)).json() == []  # предпросмотр таблицу не создал

    assert (await post({"name": "   "})).status_code == 422
    assert (await post({"name": "Т", "visibility": "public"})).status_code == 422
    assert (await post({"name": "Т" * 101})).status_code == 422
    assert (await post({"name": "Т", "columns": "не json"})).status_code == 422
    assert (await post({"name": "Т", "columns": json.dumps({"index": 0})})).status_code == 422
    assert (await post({"name": "Т", "columns": json.dumps([])})).status_code == 422
    assert (await post({"name": "Т", "columns": json.dumps([{"index": 9}])})).status_code == 422  # нет такой колонки
    assert (await post({"name": "Т", "columns": json.dumps([{"index": 0}, {"index": 0}])})).status_code == 422
    assert (await post({"name": "Т", "columns": json.dumps([{"index": 0, "data_type": "client"}])})).status_code == 422
    assert (await post({"name": "Т", "columns": json.dumps([{"index": 0, "data_type": "select"}])})).status_code == 422
    assert (await post({"name": "Т", "columns": json.dumps([{"index": 0, "data_type": "json"}])})).status_code == 422
    assert (await post({"name": "Т"}, content=b"x", filename="d.pdf")).status_code == 422
    assert (await post({"name": "Т"}, content=_csv("Название"))).status_code == 422  # одни заголовки, строк нет
    wide = _csv("|".join(f"К{i}" for i in range(51)), "|".join(["1"] * 51))
    assert (await post({"name": "Т"}, content=wide)).status_code == 422  # больше 50 колонок: нужно выбрать
    picked = json.dumps([{"index": i} for i in range(3)])
    assert (await post({"name": "Т", "columns": picked}, content=wide)).status_code == 200
    assert len((await client.get(URL, headers=h)).json()) == 1  # отклонённые запросы таблиц не создали

    monkeypatch.setattr(table_limits, "MAX_TABLES_PER_WORKSPACE", 1)
    assert (await post({"name": "Вторая"})).status_code == 409
    monkeypatch.setattr(table_limits, "MAX_TABLES_PER_WORKSPACE", 100)
    monkeypatch.setattr(row_limits, "MAX_ROWS_PER_TABLE", 0)
    assert (await post({"name": "Лимит строк"})).status_code == 409
    async with maker() as s:
        names = [t.name for t in (await s.execute(select(UserCustomTableModel))).scalars().all()]
    assert names == ["Т"]  # ни при каком отказе «пустых» таблиц не остаётся


async def test_from_file_requires_auth_and_scopes_to_company(client, world):
    _, _, logins = world
    content = _csv("Название", "Роутер")
    assert (await client.post(f"{URL}/from-file", files=_file(content), data={"name": "Т"})).status_code in (401, 403)
    ha = await _headers(client, logins, "a_manager")
    hb = await _headers(client, logins, "b_admin")
    created = await client.post(f"{URL}/from-file", files=_file(content), data={"name": "A"}, headers=ha)
    assert created.status_code == 200
    assert (await client.get(URL, headers=hb)).json() == []  # у компании B таблицы A нет
    assert (await client.get(f"{TABLES}/uct_{created.json()['table']['id']}/rows", headers=hb)).status_code == 404


async def test_import_cells_limit(client, world, monkeypatch):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    table = await _stock(client, h)
    k = table["k"]
    content = _csv("Название|Количество", "А|1", "Б|2", "В|3")  # 3 строки × 2 колонки = 6 ячеек
    mapping = {k["Название"]: 0, k["Количество"]: 1}
    monkeypatch.setattr(import_limits, "MAX_IMPORT_CELLS", 5)

    too_big = await _import(client, h, table, content, mapping)
    assert too_big.status_code == 422 and "6 ячеек" in too_big.json()["detail"]
    assert (await _import(client, h, table, content, mapping, dry_run=True)).status_code == 422  # предпросмотр тоже
    assert (
        await _import(client, h, table, content, {k["Название"]: 0})
    ).status_code == 200  # меньше колонок — проходит
    assert len(await _rows(client, h, table["id"])) == 3  # отклонённый импорт ничего не создал

    created = await client.post(f"{URL}/from-file", files=_file(content), data={"name": "Большая"}, headers=h)
    assert created.status_code == 422
    assert [t["name"] for t in (await client.get(URL, headers=h)).json()] == ["Склад"]  # таблица не создана
