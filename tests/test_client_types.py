# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_client_types.py
"""Тип клиента: компания (B2B, company) или частное лицо (B2C, person; в name — ФИО)."""

import pytest

from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


async def test_default_type_is_company(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    created = await client.post("/api/clients", json={"name": "ООО Ромашка"}, headers=h)
    assert created.status_code == 201 and created.json()["client_type"] == "company"
    # клиент, созданный до появления типа (в фикстуре без указания), — тоже компания
    assert (await client.get(f"/api/clients/{ids['ca']}", headers=h)).json()["client_type"] == "company"


async def test_create_person(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    created = await client.post(
        "/api/clients",
        json={"name": "  Иванов Иван Иванович  ", "client_type": "person", "phone": "+380501112233"},
        headers=h,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["client_type"] == "person" and body["name"] == "Иванов Иван Иванович"
    assert body["owner_id"] == ids["a_manager"]  # ответственный назначается так же, как у компании
    assert (await client.get(f"/api/clients/{body['id']}", headers=h)).json()["client_type"] == "person"


@pytest.mark.parametrize("bad", ["B2B", "individual", "", "PERSON", 5])
async def test_invalid_type_rejected(client, world, bad):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    assert (await client.post("/api/clients", json={"name": "X", "client_type": bad}, headers=h)).status_code == 422
    assert (await client.patch(f"/api/clients/{ids['ca']}", json={"client_type": bad}, headers=h)).status_code == 422


async def test_type_filter(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    await client.post("/api/clients", json={"name": "Петров Пётр", "client_type": "person"}, headers=h)
    await client.post("/api/clients", json={"name": "Сидорова Анна", "client_type": "person"}, headers=h)
    await client.post("/api/clients", json={"name": "ТОВ Альфа"}, headers=h)

    def names(resp):
        return sorted(c["name"] for c in resp.json()["items"])

    assert names(await client.get("/api/clients", params={"client_type": "person"}, headers=h)) == [
        "Петров Пётр",
        "Сидорова Анна",
    ]
    assert names(await client.get("/api/clients", params={"client_type": "company"}, headers=h)) == [
        "Ромашка",
        "ТОВ Альфа",
    ]
    assert len(names(await client.get("/api/clients", headers=h))) == 4  # без фильтра — все (до добавления Anna)
    assert (await client.get("/api/clients", params={"client_type": "bogus"}, headers=h)).status_code == 422
    # фильтр работает вместе с поиском (латиница: регистр на SQLite сравнивается только для ASCII)
    await client.post("/api/clients", json={"name": "Anna Smith", "client_type": "person"}, headers=h)
    persons = await client.get("/api/clients", params={"client_type": "person", "search": "anna"}, headers=h)
    assert names(persons) == ["Anna Smith"]
    assert names(await client.get("/api/clients", params={"client_type": "company", "search": "anna"}, headers=h)) == []


async def test_change_type_by_editor_only(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")  # ответственный за ca
    resp = await client.patch(f"/api/clients/{ids['ca']}", json={"client_type": "person"}, headers=ho)
    assert resp.status_code == 200 and resp.json()["client_type"] == "person"
    other = await _headers(client, logins, "other")
    assert (
        await client.patch(f"/api/clients/{ids['ca']}", json={"client_type": "company"}, headers=other)
    ).status_code == 403
    assert (await client.patch(f"/api/clients/{ids['ca']}", json={"client_type": None}, headers=ho)).status_code == 422
    # другие правки не сбрасывают тип
    await client.patch(f"/api/clients/{ids['ca']}", json={"phone": "123"}, headers=ho)
    assert (await client.get(f"/api/clients/{ids['ca']}", headers=ho)).json()["client_type"] == "person"


async def test_person_has_same_features_as_company(client, world):
    """Контакты, взаимодействия и сделки у частного лица работают так же, как у компании."""
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    person = (
        await client.post("/api/clients", json={"name": "Коваль Олег", "client_type": "person"}, headers=h)
    ).json()
    base = f"/api/clients/{person['id']}"
    assert (await client.post(f"{base}/contacts", json={"name": "Жена"}, headers=h)).status_code == 201
    assert (
        await client.post(f"{base}/interactions", json={"type": "call", "summary": "Позвонил"}, headers=h)
    ).status_code == 201
    deal = await client.post(
        f"{base}/deals", json={"title": "Консультация", "amount": 500, "currency": "UAH"}, headers=h
    )
    assert deal.status_code == 201
    assert (await client.patch(base, json={"next_contact_at": None}, headers=h)).status_code == 200


async def test_other_company_cannot_see_person(client, world):
    _, _, logins = world
    ha = await _headers(client, logins, "a_manager")
    person = (await client.post("/api/clients", json={"name": "Частный", "client_type": "person"}, headers=ha)).json()
    hb = await _headers(client, logins, "b_admin")
    assert (await client.get(f"/api/clients/{person['id']}", headers=hb)).status_code == 404
    assert [
        c["name"]
        for c in (await client.get("/api/clients", params={"client_type": "person"}, headers=hb)).json()["items"]
    ] == []


# ── поля частного лица: дата рождения и пол ──────────────────────────────────
async def test_person_birth_date_and_gender(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    created = await client.post(
        "/api/clients",
        json={"name": "Коваль Олег", "client_type": "person", "birth_date": "1990-03-05", "gender": "male"},
        headers=h,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["birth_date"] == "1990-03-05" and body["gender"] == "male"
    url = f"/api/clients/{body['id']}"
    changed = await client.patch(url, json={"gender": "female", "birth_date": "1991-04-06"}, headers=h)
    assert changed.json()["gender"] == "female" and changed.json()["birth_date"] == "1991-04-06"
    cleared = await client.patch(url, json={"gender": None, "birth_date": None}, headers=h)
    assert cleared.status_code == 200 and cleared.json()["gender"] is None and cleared.json()["birth_date"] is None
    # необязательны
    assert (
        await client.post("/api/clients", json={"name": "Без полей", "client_type": "person"}, headers=h)
    ).status_code == 201


async def test_company_cannot_have_person_fields(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    for extra in ({"birth_date": "1990-03-05"}, {"gender": "male"}):
        assert (await client.post("/api/clients", json={"name": "ООО", **extra}, headers=h)).status_code == 422
        assert (await client.patch(f"/api/clients/{ids['ca']}", json=extra, headers=h)).status_code == 422
    # компания, в запросе тип person и поля — можно (тип меняется одновременно)
    ok = await client.patch(f"/api/clients/{ids['ca']}", json={"client_type": "person", "gender": "male"}, headers=h)
    assert ok.status_code == 200 and ok.json()["client_type"] == "person" and ok.json()["gender"] == "male"
    # а тип компания + поля в одном запросе — нет
    bad = await client.patch(
        f"/api/clients/{ids['ca']}", json={"client_type": "company", "birth_date": "1990-03-05"}, headers=h
    )
    assert bad.status_code == 422


async def test_switching_to_company_clears_person_fields(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    person = (
        await client.post(
            "/api/clients",
            json={"name": "Частник", "client_type": "person", "birth_date": "1985-01-02", "gender": "female"},
            headers=h,
        )
    ).json()
    resp = await client.patch(f"/api/clients/{person['id']}", json={"client_type": "company"}, headers=h)
    assert resp.status_code == 200
    assert resp.json()["birth_date"] is None and resp.json()["gender"] is None  # у компании этих данных нет
    back = await client.patch(f"/api/clients/{person['id']}", json={"client_type": "person"}, headers=h)
    assert back.json()["birth_date"] is None  # назад они не возвращаются


@pytest.mark.parametrize("birth", ["2999-01-01", "1899-12-31", "not-a-date"])
async def test_invalid_birth_date(client, world, birth):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    assert (
        await client.post("/api/clients", json={"name": "X", "client_type": "person", "birth_date": birth}, headers=h)
    ).status_code == 422


@pytest.mark.parametrize("gender", ["other", "M", "", 1])
async def test_invalid_gender(client, world, gender):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    resp = await client.post("/api/clients", json={"name": "X", "client_type": "person", "gender": gender}, headers=h)
    assert resp.status_code == 422
