# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_crm_export.py
"""Экспорт клиентов и сделок в CSV: права, изоляция компаний, формат для Excel, защита от формул, обратный импорт."""

import csv
import io
import json

import pytest

from src.services.crm_export_service import safe_cell
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


def _parse(response) -> list[dict]:
    """CSV-ответ → список словарей. BOM должен быть: без него Excel ломает кириллицу."""
    assert response.content.startswith(b"\xef\xbb\xbf"), "нужен UTF-8 BOM"
    text = response.content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


async def _create_client(client, headers, **payload):
    resp = await client.post("/api/clients", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── безопасная ячейка ────────────────────────────────────────────────────────
@pytest.mark.parametrize("value", ["=1+1", "@SUM(A1)", "\t=x", "-cmd|' /C calc'!A0", "+cmd", '=HYPERLINK("http://x")'])
def test_safe_cell_neutralizes_formulas(value):
    assert safe_cell(value).startswith("'")


@pytest.mark.parametrize("value", ["+380 50 111-22-33", "-5", "8 (912) 345-67-89", "Ромашка", "a=b", "", None])
def test_safe_cell_keeps_normal_values(value):
    assert safe_cell(value) == ("" if value is None else value)


# ── клиенты ──────────────────────────────────────────────────────────────────
async def test_clients_export_format_and_scope(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    await _create_client(
        client,
        h,
        name="Иван Петров",
        client_type="person",
        phone="+380501112233",
        email="ivan@x.ru",
        birth_date="1985-03-05",
        gender="male",
        next_contact_at="2099-01-02",
    )
    resp = await client.get("/api/clients/export", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "clients_export_" in resp.headers["content-disposition"]
    rows = _parse(resp)
    names = {r["Название"] for r in rows}
    assert names == {"Ромашка", "Иван Петров"}  # «Лютик» из компании B не попал
    ivan = next(r for r in rows if r["Название"] == "Иван Петров")
    assert ivan["Тип"] == "Частное лицо" and ivan["Пол"] == "Мужской"
    assert ivan["Дата рождения"] == "05.03.1985" and ivan["Связаться снова"] == "02.01.2099"
    assert ivan["Телефон"] == "+380501112233" and ivan["Ответственный"] == "a_manager"


async def test_clients_export_filters(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    await _create_client(client, h, name="Иван Петров", client_type="person")
    await _create_client(client, h, name="ООО Лотос")
    people = _parse(await client.get("/api/clients/export", params={"client_type": "person"}, headers=h))
    assert [r["Название"] for r in people] == ["Иван Петров"]
    found = _parse(await client.get("/api/clients/export", params={"search": "Лотос"}, headers=h))
    assert [r["Название"] for r in found] == ["ООО Лотос"]
    mine = _parse(await client.get("/api/clients/export", params={"owner_id": ids["owner"]}, headers=h))
    assert [r["Название"] for r in mine] == ["Ромашка"]


async def test_exports_require_manager_role(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    assert (await client.get("/api/clients/export", headers=h)).status_code == 403
    assert (await client.get("/api/deals/export", headers=h)).status_code == 403


async def test_clients_export_neutralizes_formulas_but_not_phones(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    await _create_client(client, h, name='=HYPERLINK("http://evil")', phone="+380501112233", notes="@cmd")
    rows = _parse(await client.get("/api/clients/export", headers=h))
    evil = next(r for r in rows if "HYPERLINK" in r["Название"])
    assert evil["Название"].startswith("'=") and evil["Заметки"] == "'@cmd" and evil["Телефон"] == "+380501112233"


async def test_exported_clients_can_be_imported_back_as_duplicates(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    await _create_client(client, h, name="Иван Петров", client_type="person", phone="+380501112233", gender="male")
    await _create_client(client, h, name="ООО Лотос", email="info@lotos.ru", address="Харьков")
    exported = (await client.get("/api/clients/export", headers=h)).content

    columns = await client.post(
        "/api/clients/import/columns", files={"file": ("c.csv", exported, "text/csv")}, headers=h
    )
    assert columns.status_code == 200, columns.text
    suggested = {c["suggested"]: c["index"] for c in columns.json()["columns"] if c["suggested"]}
    assert {"name", "client_type", "phone", "email", "address", "notes", "owner", "birth_date", "gender"} <= set(
        suggested
    )

    resp = await client.post(
        "/api/clients/import",
        files={"file": ("c.csv", exported, "text/csv")},
        data={"mapping": json.dumps(suggested), "dry_run": "true"},
        headers=h,
    )
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["errors"] == [] and body["to_create"] == 0 and body["skipped_duplicates"] == 3


# ── сделки ───────────────────────────────────────────────────────────────────
async def test_deals_export_content_scope_and_filters(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    created = await client.post(
        f"/api/clients/{ids['ca']}/deals", json={"title": "Поставка", "amount": 1500.5, "currency": "UAH"}, headers=h
    )
    assert created.status_code == 201, created.text
    other = await client.post(f"/api/clients/{ids['ca']}/deals", json={"title": "=cmd"}, headers=h)
    assert other.status_code == 201
    hb = await _headers(client, logins, "b_admin")
    foreign = await client.post(f"/api/clients/{ids['cb']}/deals", json={"title": "Чужая"}, headers=hb)
    assert foreign.status_code == 201

    resp = await client.get("/api/deals/export", headers=h)
    assert resp.status_code == 200 and "deals_export_" in resp.headers["content-disposition"]
    rows = _parse(resp)
    assert {r["Название"] for r in rows} == {"Поставка", "'=cmd"}
    deal = next(r for r in rows if r["Название"] == "Поставка")
    assert deal["Клиент"] == "Ромашка" and deal["Стадия"] == "Новая" and deal["Статус"] == "В работе"
    assert deal["Сумма"] == "1500.50" and deal["Валюта"] == "UAH" and deal["Ответственный"] == "a_manager"

    by_owner = _parse(await client.get("/api/deals/export", params={"owner_id": ids["owner"]}, headers=h))
    assert by_owner == []
    by_client = _parse(await client.get("/api/deals/export", params={"client_id": ids["ca"]}, headers=h))
    assert len(by_client) == 2
    by_type = _parse(await client.get("/api/deals/export", params={"client_type": "person"}, headers=h))
    assert by_type == []


async def test_deals_export_empty_has_header_only(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")
    resp = await client.get("/api/deals/export", headers=h)
    assert resp.status_code == 200 and _parse(resp) == []
    assert resp.content.decode("utf-8-sig").startswith("ID;Название;Клиент;Стадия")
