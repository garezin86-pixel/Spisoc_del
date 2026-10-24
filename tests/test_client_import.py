# tests/test_client_import.py
"""Импорт клиентов из CSV/XLSX: сопоставление колонок, предпросмотр, дубликаты, права, изоляция компаний."""

import io
import json
import uuid
from datetime import date

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.security import hash_password
from src.models.client import ClientModel
from src.models.user import UserModel
from src.models.workspace import WorkspaceModel
from src.services import client_import_service as svc
from src.services.client_import_service import email_key, infer_client_type, name_key, phone_key, suggest_mapping

PASSWORD = "password123"
CSV = "text/csv"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _user(name: str, ws_id: int, role: str = "user") -> UserModel:
    return UserModel(
        username=name,
        login=f"{name}_{uuid.uuid4().hex[:6]}",
        password_hash=hash_password(PASSWORD),
        role=role,
        workspace_id=ws_id,
    )


@pytest.fixture
async def world(engine):
    """Компания A: admin, manager, обычный пользователь, клиент «Ромашка» без телефона и клиент «Василёк» с телефоном.
    Компания B: admin и клиент с телефоном +380 98 111 22 33 (в A он дубликатом считаться не должен)."""
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        a = WorkspaceModel(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
        b = WorkspaceModel(name="B", slug=f"b-{uuid.uuid4().hex[:6]}")
        s.add_all([a, b])
        await s.commit()
        users = {
            "a_admin": _user("a_admin", a.id, "admin"),
            "a_manager": _user("a_manager", a.id, "manager"),
            "plain": _user("plain", a.id),
            "b_admin": _user("b_admin", b.id, "admin"),
        }
        s.add_all(users.values())
        await s.commit()
        s.add_all(
            [
                ClientModel(name="Ромашка", workspace_id=a.id, owner_id=users["a_admin"].id),
                ClientModel(
                    name="Василёк", phone="+38 (067) 123-45-67", workspace_id=a.id, owner_id=users["a_admin"].id
                ),
                ClientModel(name="Чужой", phone="+380981112233", workspace_id=b.id, owner_id=users["b_admin"].id),
            ]
        )
        await s.commit()
        logins = {k: u.login for k, u in users.items()}
        ids = {"a": a.id, "b": b.id, **{k: u.id for k, u in users.items()}}
    return maker, ids, logins


async def _headers(client, logins: dict, who: str) -> dict:
    resp = await client.post("/auth/login", json={"username": logins[who], "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _import(client, headers, content: bytes, mapping: dict, *, filename="clients.csv", mime=CSV, **form):
    data = {
        "mapping": json.dumps(mapping),
        **{k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in form.items()},
    }
    return await client.post(
        "/api/clients/import", files={"file": (filename, content, mime)}, data=data, headers=headers
    )


async def _names(maker, ws_id: int) -> set[str]:
    async with maker() as s:
        rows = await s.execute(select(ClientModel.name).where(ClientModel.workspace_id == ws_id))
        return set(rows.scalars().all())


# ── чистые функции ───────────────────────────────────────────────────────────
def test_suggest_mapping_by_russian_and_english_headers():
    header = ["Название", "Телефон", "E-mail", "Адрес", "Комментарий", "Ответственный", "Что-то лишнее"]
    assert suggest_mapping(header) == {"name": 0, "phone": 1, "email": 2, "address": 3, "notes": 4, "owner": 5}
    assert suggest_mapping(["Company", "Phone", "Mail"]) == {"name": 0, "phone": 1, "email": 2}


def test_name_column_is_found_by_words_in_header():
    assert suggest_mapping(["ФИО / Компания", "Тел.", "E-mail"]) == {"name": 0, "phone": 1, "email": 2}
    assert suggest_mapping(["№", "Название компании", "Телефон"]) == {"name": 1, "phone": 2}


def test_word_search_is_only_for_name_and_does_not_steal_columns():
    # «Адрес электронной почты» не должен стать ни названием, ни адресом
    assert suggest_mapping(["Адрес электронной почты", "Телефон"]) == {"phone": 1}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Лебедев Сергей", "person"),
        ("Иванов Иван Петрович", "person"),
        ("Анна-Мария Ковальчук", "person"),
        ("ООО «Аврора-Сервис»", "company"),
        ("ТОВ Ромашка", "company"),
        ("ФОП Петренко Иван", "company"),
        ("Ромашка и компания", "company"),
        ("Нормальный Клиент 2", "company"),
        ("Ромашка", "company"),
        ("Acme LLC", "company"),
    ],
)
def test_infer_client_type_from_name(name, expected):
    assert infer_client_type(name) == expected


def test_suggest_mapping_uses_each_field_once():
    assert suggest_mapping(["Имя", "Клиент"]) == {"name": 0}


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("+380 98 765-43-21", "098 765 43 21"),
        ("8 (912) 345-67-89", "+7 912 345 67 89"),
        ("380987654321.0".split(".")[0], "0987654321"),
    ],
)
def test_phone_key_ignores_formatting_and_country_code(a, b):
    assert phone_key(a) == phone_key(b) is not None


def test_phone_key_ignores_too_short_numbers():
    assert phone_key("12-34") is None and phone_key(None) is None


def test_email_and_name_keys_are_normalized():
    assert email_key("  Info@Mail.RU ") == "info@mail.ru" and email_key("  ") is None
    assert name_key("  ООО   Ромашка ", "company") == ("ооо ромашка", "company")


# ── колонки ──────────────────────────────────────────────────────────────────
async def test_columns_endpoint_suggests_mapping_and_samples(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    content = "Клиент;Тел;Прочее\nАльфа;+380501112233;x\nБета;;y\n".encode("cp1251")
    resp = await client.post("/api/clients/import/columns", files={"file": ("c.csv", content, CSV)}, headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 2
    assert [c["suggested"] for c in body["columns"]] == ["name", "phone", None]
    assert body["columns"][0]["samples"] == ["Альфа", "Бета"]
    assert any(f["key"] == "name" and f["required"] for f in body["fields"])


async def test_columns_rejects_unsupported_and_broken_files(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    resp = await client.post("/api/clients/import/columns", files={"file": ("c.txt", b"a", "text/plain")}, headers=h)
    assert resp.status_code == 422
    resp = await client.post(
        "/api/clients/import/columns", files={"file": ("c.xlsx", b"not an excel", XLSX)}, headers=h
    )
    assert resp.status_code == 422


async def test_plain_user_cannot_import_or_inspect(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "plain")
    resp = await client.post("/api/clients/import/columns", files={"file": ("c.csv", b"a\n1", CSV)}, headers=h)
    assert resp.status_code == 403
    resp = await _import(client, h, "Название\nX\n".encode(), {"name": 0})
    assert resp.status_code == 403


# ── предпросмотр и создание ──────────────────────────────────────────────────
async def test_dry_run_reports_without_creating(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    content = (
        "Название,Телефон,Email,Дата рождения\n"
        "Альфа,+380501112233,a@x.ru,\n"
        ",+380501112244,,\n"  # пустое название
        "Бета,,не-почта,\n"  # плохой email
        "Гамма,,,01.02.1990\n"  # дата рождения у компании — отбрасывается
    ).encode()
    before = await _names(maker, ids["a"])
    resp = await _import(client, h, content, {"name": 0, "phone": 1, "email": 2, "birth_date": 3}, dry_run=True)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is True and body["created"] == 0
    assert body["total_rows"] == 4 and body["to_create"] == 2
    assert [e["row"] for e in body["errors"]] == [3, 4]
    assert "пустое название" in body["errors"][0]["message"] and "email" in body["errors"][1]["message"].lower()
    assert body["warnings"][0]["row"] == 5 and "только у частного лица" in body["warnings"][0]["message"]
    assert [p["name"] for p in body["preview"]] == ["Альфа", "Гамма"]
    assert await _names(maker, ids["a"]) == before


async def test_import_creates_clients_with_owner_types_and_person_fields(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    content = (
        "ФИО;Тип;Пол;Дата рождения;Ответственный;Заметки\n"
        f"Иван Петров;частное лицо;м;05.03.1985;{logins['a_admin']};важный\n"
        "ООО Лотос;компания;;;нет-такого;\n"
        "Анна;физлицо;ж;1990-07-01;;\n"
    ).encode("cp1251")
    mapping = {"name": 0, "client_type": 1, "gender": 2, "birth_date": 3, "owner": 4, "notes": 5}
    resp = await _import(client, h, content, mapping)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 3 and body["errors"] == []
    assert [w["row"] for w in body["warnings"]] == [3] and "нет-такого" in body["warnings"][0]["message"]

    async with maker() as s:
        rows = {
            c.name: c
            for c in (await s.execute(select(ClientModel).where(ClientModel.workspace_id == ids["a"]))).scalars()
        }
    ivan, lotus, anna = rows["Иван Петров"], rows["ООО Лотос"], rows["Анна"]
    assert (ivan.client_type, ivan.gender, ivan.birth_date, ivan.notes) == (
        "person",
        "male",
        date(1985, 3, 5),
        "важный",
    )
    assert ivan.owner_id == ids["a_admin"]  # по логину из файла
    assert lotus.client_type == "company" and lotus.owner_id == ids["a_manager"]  # не найден → тот, кто импортирует
    assert (anna.client_type, anna.gender, anna.birth_date) == ("person", "female", date(1990, 7, 1))
    assert anna.owner_id == ids["a_manager"]


async def test_default_type_applies_when_column_is_not_mapped(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    resp = await _import(client, h, "Имя\nПетя\n".encode(), {"name": 0}, default_type="person")
    assert resp.status_code == 200 and resp.json()["created"] == 1
    async with maker() as s:
        petya = (await s.execute(select(ClientModel).where(ClientModel.name == "Петя"))).scalar_one()
    assert petya.client_type == "person"


# ── дубликаты ────────────────────────────────────────────────────────────────
async def test_duplicates_are_skipped_against_existing_and_within_file(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    content = (
        "Название,Телефон,Email\n"
        "Другое имя,0671234567,\n"  # телефон Василька в другом формате
        "Ромашка,,\n"  # такая же компания без телефона/email
        "Новый,+380509998877,new@x.ru\n"
        "Новый дубль,0509998877,\n"  # тот же телефон внутри файла
        "Ещё один,,NEW@x.ru\n"  # тот же email внутри файла
        "Чужой,+380981112233,\n"  # телефон клиента из ДРУГОЙ компании — не дубликат
    ).encode()
    resp = await _import(client, h, content, {"name": 0, "phone": 1, "email": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 2 and body["skipped_duplicates"] == 4
    assert sorted(d["row"] for d in body["duplicates"]) == [2, 3, 5, 6]
    names = await _names(maker, ids["a"])
    assert {"Новый", "Чужой"} <= names and not ({"Другое имя", "Новый дубль", "Ещё один"} & names)


async def test_skip_duplicates_false_creates_everything(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    resp = await _import(client, h, "Название\nРомашка\n".encode(), {"name": 0}, skip_duplicates=False)
    assert resp.status_code == 200 and resp.json()["created"] == 1 and resp.json()["skipped_duplicates"] == 0
    async with maker() as s:
        count = len((await s.execute(select(ClientModel).where(ClientModel.name == "Ромашка"))).scalars().all())
    assert count == 2


# ── XLSX ─────────────────────────────────────────────────────────────────────
async def test_xlsx_with_numeric_phone_and_date_cells(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    wb = Workbook()
    ws = wb.active
    ws.append(["Название", "Телефон", "Тип", "Дата рождения"])
    ws.append(["Мария", 380991112200, "person", date(1992, 12, 31)])
    buffer = io.BytesIO()
    wb.save(buffer)
    resp = await _import(
        client,
        h,
        buffer.getvalue(),
        {"name": 0, "phone": 1, "client_type": 2, "birth_date": 3},
        filename="c.xlsx",
        mime=XLSX,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1 and resp.json()["warnings"] == []
    async with maker() as s:
        maria = (await s.execute(select(ClientModel).where(ClientModel.name == "Мария"))).scalar_one()
    assert maria.phone == "380991112200" and maria.birth_date == date(1992, 12, 31)


# ── ошибки сопоставления ─────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "mapping",
    [{}, {"phone": 0}, {"name": 0, "phone": 0}, {"name": 5}, {"name": 0, "nonsense": 1}, {"name": -1}],
)
async def test_bad_mapping_is_rejected(client, world, mapping):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    resp = await _import(client, h, "Название,Телефон\nX,1\n".encode(), mapping)
    assert resp.status_code == 422, resp.text


async def test_mapping_must_be_json_object(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    for bad in ("не json", "[0, 1]", '{"name": "0"}'):
        resp = await client.post(
            "/api/clients/import", files={"file": ("c.csv", b"a\nb\n", CSV)}, data={"mapping": bad}, headers=h
        )
        assert resp.status_code == 422, bad


async def test_row_limit_is_enforced(client, world, monkeypatch):
    _, _, logins = world
    monkeypatch.setattr(svc, "MAX_IMPORT_ROWS", 2)
    h = await _headers(client, logins, "a_manager")
    resp = await _import(client, h, "Название\nA\nB\nC\n".encode(), {"name": 0})
    assert resp.status_code == 422 and "Слишком много строк" in resp.json()["detail"]


async def test_file_without_rows_creates_nothing(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    before = await _names(maker, ids["a"])
    resp = await _import(client, h, "Название\n".encode(), {"name": 0})
    assert resp.status_code == 200 and resp.json()["created"] == 0 and resp.json()["total_rows"] == 0
    assert await _names(maker, ids["a"]) == before


async def test_imported_clients_are_scoped_to_company(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    await _import(client, h, "Название\nТолько А\n".encode(), {"name": 0})
    assert "Только А" in await _names(maker, ids["a"]) and "Только А" not in await _names(maker, ids["b"])


async def test_auto_type_guesses_by_name_and_respects_the_type_column(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    content = "Название,Тип\nИванов Иван,\nООО «Лотос»,\nПетров Пётр,компания\nСидоров Сидор,непонятно\n".encode()
    resp = await _import(client, h, content, {"name": 0, "client_type": 1}, default_type="auto")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["default_type"] == "auto" and body["created"] == 4
    assert [w["row"] for w in body["warnings"]] == [5] and "определён по названию" in body["warnings"][0]["message"]
    async with maker() as s:
        types = {c.name: c.client_type for c in (await s.execute(select(ClientModel))).scalars()}
    assert types["Иванов Иван"] == "person" and types["ООО «Лотос»"] == "company"
    assert types["Петров Пётр"] == "company"  # колонка с типом важнее догадки
    assert types["Сидоров Сидор"] == "person"


async def test_unknown_default_type_is_rejected(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    resp = await _import(client, h, "Название\nX\n".encode(), {"name": 0}, default_type="robot")
    assert resp.status_code == 422
