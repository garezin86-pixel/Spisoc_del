# tests/test_clients.py
"""Этап 1 lite-CRM: клиенты и контакты.

Главный риск — утечка клиентов между компаниями (workspace) и неверные права.
Поэтому почти все сценарии идут через HTTP с двумя компаниями A и B.
"""

import uuid

import pytest
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.security import hash_password
from src.models.audit import AuditAction, AuditLog
from src.models.client import ClientModel, ContactModel
from src.models.project import ProjectModel
from src.models.user import UserModel
from src.models.workspace import WorkspaceModel

PASSWORD = "password123"


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
    """Две компании. В A: admin, manager, owner (обычный, ответственный за ca), other (обычный).
    В B: admin. Клиент ca (ответственный owner) в A, клиент cb в B. Создаётся платформенной сессией."""
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        a = WorkspaceModel(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
        b = WorkspaceModel(name="B", slug=f"b-{uuid.uuid4().hex[:6]}")
        s.add_all([a, b])
        await s.commit()

        users = {
            "a_admin": _user("a_admin", a.id, "admin"),
            "a_manager": _user("a_manager", a.id, "manager"),
            "owner": _user("owner", a.id),
            "other": _user("other", a.id),
            "b_admin": _user("b_admin", b.id, "admin"),
        }
        s.add_all(users.values())
        await s.commit()

        ca = ClientModel(name="Ромашка", workspace_id=a.id, owner_id=users["owner"].id)
        cb = ClientModel(name="Лютик", workspace_id=b.id, owner_id=users["b_admin"].id)
        s.add_all([ca, cb])
        await s.commit()

        logins = {k: u.login for k, u in users.items()}
        ids = {"a": a.id, "b": b.id, "ca": ca.id, "cb": cb.id, **{k: u.id for k, u in users.items()}}
    return maker, ids, logins


async def _headers(client, logins: dict, who: str) -> dict:
    resp = await client.post("/auth/login", json={"username": logins[who], "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── создание и права ─────────────────────────────────────────────────────────
async def test_manager_creates_client_and_becomes_owner(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    resp = await client.post("/api/clients", json={"name": "  Новый  ", "email": "x@y.ru"}, headers=h)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Новый"
    assert body["owner_id"] == ids["a_manager"]


async def test_plain_user_cannot_create(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    resp = await client.post("/api/clients", json={"name": "X"}, headers=h)
    assert resp.status_code == 403


async def test_duplicate_names_allowed(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")
    r1 = await client.post("/api/clients", json={"name": "Ромашка"}, headers=h)
    r2 = await client.post("/api/clients", json={"name": "Ромашка"}, headers=h)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


@pytest.mark.parametrize(
    "payload",
    [{"name": ""}, {"name": "   "}, {"name": "X", "email": "not-an-email"}, {}],
)
async def test_create_validation(client, world, payload):
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")
    resp = await client.post("/api/clients", json=payload, headers=h)
    assert resp.status_code == 422


async def test_owner_can_edit_but_not_reassign_or_delete(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "owner")
    resp = await client.patch(f"/api/clients/{ids['ca']}", json={"phone": "+380501112233"}, headers=h)
    assert resp.status_code == 200 and resp.json()["phone"] == "+380501112233"

    resp = await client.patch(f"/api/clients/{ids['ca']}", json={"owner_id": ids["other"]}, headers=h)
    assert resp.status_code == 403

    resp = await client.delete(f"/api/clients/{ids['ca']}", headers=h)
    assert resp.status_code == 403


async def test_non_owner_user_can_read_but_not_edit(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "other")
    assert (await client.get(f"/api/clients/{ids['ca']}", headers=h)).status_code == 200
    assert (await client.get(f"/api/clients/{ids['ca']}/contacts", headers=h)).status_code == 200
    assert (await client.patch(f"/api/clients/{ids['ca']}", json={"name": "Z"}, headers=h)).status_code == 403
    assert (await client.post(f"/api/clients/{ids['ca']}/contacts", json={"name": "Z"}, headers=h)).status_code == 403


async def test_manager_reassigns_owner_and_null_clears_field(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    resp = await client.patch(f"/api/clients/{ids['ca']}", json={"owner_id": ids["other"]}, headers=h)
    assert resp.status_code == 200 and resp.json()["owner_id"] == ids["other"]

    await client.patch(f"/api/clients/{ids['ca']}", json={"phone": "123"}, headers=h)
    resp = await client.patch(f"/api/clients/{ids['ca']}", json={"phone": None}, headers=h)
    assert resp.json()["phone"] is None
    # название очистить нельзя
    resp = await client.patch(f"/api/clients/{ids['ca']}", json={"name": None}, headers=h)
    assert resp.status_code == 422


# ── изоляция компаний ────────────────────────────────────────────────────────
async def test_list_is_scoped_to_company(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    hb = await _headers(client, logins, "b_admin")
    names_a = [c["name"] for c in (await client.get("/api/clients", headers=ha)).json()["items"]]
    names_b = [c["name"] for c in (await client.get("/api/clients", headers=hb)).json()["items"]]
    assert names_a == ["Ромашка"]
    assert names_b == ["Лютик"]


async def test_foreign_client_is_404_for_every_operation(client, world):
    _, ids, logins = world
    hb = await _headers(client, logins, "b_admin")  # админ другой компании — максимум прав
    cid = ids["ca"]
    assert (await client.get(f"/api/clients/{cid}", headers=hb)).status_code == 404
    assert (await client.patch(f"/api/clients/{cid}", json={"name": "взлом"}, headers=hb)).status_code == 404
    assert (await client.delete(f"/api/clients/{cid}", headers=hb)).status_code == 404
    assert (await client.get(f"/api/clients/{cid}/contacts", headers=hb)).status_code == 404
    assert (await client.post(f"/api/clients/{cid}/contacts", json={"name": "X"}, headers=hb)).status_code == 404

    # и ничего не изменилось
    ha = await _headers(client, logins, "a_admin")
    assert (await client.get(f"/api/clients/{cid}", headers=ha)).json()["name"] == "Ромашка"


async def test_foreign_contact_is_404(client, world):
    maker, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    created = await client.post(f"/api/clients/{ids['ca']}/contacts", json={"name": "Иван"}, headers=ha)
    contact_id = created.json()["id"]

    hb = await _headers(client, logins, "b_admin")
    # контакт чужого клиента — и по «своему» client_id тоже не достать
    for client_id in (ids["ca"], ids["cb"]):
        assert (
            await client.patch(f"/api/clients/{client_id}/contacts/{contact_id}", json={"name": "X"}, headers=hb)
        ).status_code == 404
        assert (await client.delete(f"/api/clients/{client_id}/contacts/{contact_id}", headers=hb)).status_code == 404


async def test_owner_id_from_other_company_rejected(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    resp = await client.post("/api/clients", json={"name": "X", "owner_id": ids["b_admin"]}, headers=ha)
    assert resp.status_code == 404
    resp = await client.patch(f"/api/clients/{ids['ca']}", json={"owner_id": ids["b_admin"]}, headers=ha)
    assert resp.status_code == 404


# ── поиск и пагинация ────────────────────────────────────────────────────────
async def test_search_is_case_insensitive_and_literal(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")
    for name, phone in [("Alpha Build", "+3801"), ("100% Milk", None), ("Beta_Group", None), ("Альфа Строй", None)]:
        await client.post("/api/clients", json={"name": name, "phone": phone}, headers=h)

    def names(resp):
        return sorted(c["name"] for c in resp.json()["items"])

    async def search(text):
        return names(await client.get("/api/clients", params={"search": text}, headers=h))

    # Регистр: на Latin; кириллицу SQLite в тестах регистронезависимо не сравнивает (на Postgres ILIKE — да),
    # поэтому для неё проверяем только точное совпадение регистра.
    assert await search("alpha") == ["Alpha Build"]
    assert await search("Альфа") == ["Альфа Строй"]
    assert await search("+3801") == ["Alpha Build"]  # по телефону
    # % и _ ищутся буквально, а не как шаблоны
    assert await search("%") == ["100% Milk"]
    assert await search("b_t") == []  # как шаблон совпал бы с "Beta"
    assert await search("beta_g") == ["Beta_Group"]


async def test_pagination(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")
    for i in range(4):
        await client.post("/api/clients", json={"name": f"Клиент {i}"}, headers=h)
    resp = await client.get("/api/clients", params={"page": 2, "size": 2}, headers=h)
    body = resp.json()
    assert body["total"] == 5 and body["pages"] == 3 and len(body["items"]) == 2


# ── контакты, мягкое удаление, аудит ─────────────────────────────────────────
async def test_contacts_crud_and_cascade_soft_delete(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "owner")  # ответственный ведёт контакты
    c1 = await client.post(
        f"/api/clients/{ids['ca']}/contacts", json={"name": "Иван", "position": "Директор"}, headers=h
    )
    c2 = await client.post(f"/api/clients/{ids['ca']}/contacts", json={"name": "Пётр"}, headers=h)
    assert c1.status_code == c2.status_code == 201

    resp = await client.patch(f"/api/clients/{ids['ca']}/contacts/{c1.json()['id']}", json={"phone": "555"}, headers=h)
    assert resp.status_code == 200 and resp.json()["phone"] == "555"

    resp = await client.delete(f"/api/clients/{ids['ca']}/contacts/{c2.json()['id']}", headers=h)
    assert resp.status_code == 200
    listed = (await client.get(f"/api/clients/{ids['ca']}/contacts", headers=h)).json()
    assert [c["name"] for c in listed] == ["Иван"]

    # удаление клиента менеджером гасит клиента и оставшиеся контакты
    hm = await _headers(client, logins, "a_manager")
    assert (await client.delete(f"/api/clients/{ids['ca']}", headers=hm)).status_code == 200
    assert (await client.get(f"/api/clients/{ids['ca']}", headers=hm)).status_code == 404
    assert (await client.get(f"/api/clients/{ids['ca']}/contacts", headers=hm)).status_code == 404
    assert (await client.get("/api/clients", headers=hm)).json()["total"] == 0

    async with maker() as s:  # физически строки на месте, но помечены
        rows = (await s.execute(select(ContactModel).where(ContactModel.client_id == ids["ca"]))).scalars().all()
        assert len(rows) == 2 and all(r.deleted_at is not None for r in rows)
        row = (await s.execute(select(ClientModel).where(ClientModel.id == ids["ca"]))).scalar_one()
        assert row.deleted_at is not None


async def test_audit_events_carry_workspace_and_user(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    created = (await client.post("/api/clients", json={"name": "Аудит"}, headers=h)).json()
    cid = created["id"]
    await client.patch(f"/api/clients/{cid}", json={"phone": "777"}, headers=h)
    contact = (await client.post(f"/api/clients/{cid}/contacts", json={"name": "Анна"}, headers=h)).json()
    await client.delete(f"/api/clients/{cid}", headers=h)

    async with maker() as s:  # платформенная сессия видит всё
        rows = (
            (
                await s.execute(
                    select(AuditLog).where(
                        or_(
                            and_(AuditLog.entity_type == "clients", AuditLog.entity_id == cid),
                            and_(AuditLog.entity_type == "contacts", AuditLog.entity_id == contact["id"]),
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
    by_key = {(r.entity_type, r.action) for r in rows}
    assert ("clients", AuditAction.create) in by_key
    assert ("clients", AuditAction.update) in by_key
    assert ("clients", AuditAction.delete) in by_key
    assert ("contacts", AuditAction.create) in by_key
    assert ("contacts", AuditAction.delete) in by_key  # каскадное удаление контакта тоже в аудите
    assert all(r.workspace_id == ids["a"] for r in rows)
    assert all(r.user_id == ids["a_manager"] for r in rows)


async def test_activity_feed_ignores_client_events(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")
    await client.post("/api/clients", json={"name": "Для ленты"}, headers=h)
    resp = await client.get("/api/analytics/activity", headers=h)
    assert resp.status_code == 200
    assert all(item["entity_type"] in ("spisok_del", "comments") for item in resp.json()["items"])


# ── привязка проекта к клиенту ───────────────────────────────────────────────
async def _make_project(client, headers, **extra) -> dict:
    resp = await client.post("/api/projects", json={"name": "Проект", **extra}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_project_can_be_bound_to_own_client(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    project = await _make_project(client, h, client_id=ids["ca"])
    assert project["client_id"] == ids["ca"]

    other = await _make_project(client, h)
    assert other["client_id"] is None
    resp = await client.patch(f"/api/projects/{other['id']}/client", json={"client_id": ids["ca"]}, headers=h)
    assert resp.status_code == 200 and resp.json()["client_id"] == ids["ca"]

    resp = await client.patch(f"/api/projects/{other['id']}/client", json={"client_id": None}, headers=h)
    assert resp.status_code == 200 and resp.json()["client_id"] is None


async def test_project_cannot_bind_foreign_client(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    resp = await client.post("/api/projects", json={"name": "П", "client_id": ids["cb"]}, headers=h)
    assert resp.status_code == 404

    project = await _make_project(client, h)
    resp = await client.patch(f"/api/projects/{project['id']}/client", json={"client_id": ids["cb"]}, headers=h)
    assert resp.status_code == 404

    async with maker() as s:  # в БД ничего не привязалось
        row = (await s.execute(select(ProjectModel).where(ProjectModel.id == project["id"]))).scalar_one()
        assert row.client_id is None


async def test_project_cannot_bind_deleted_client(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    created = (await client.post("/api/clients", json={"name": "Скоро удалят"}, headers=h)).json()
    await client.delete(f"/api/clients/{created['id']}", headers=h)
    resp = await client.post("/api/projects", json={"name": "П", "client_id": created["id"]}, headers=h)
    assert resp.status_code == 404


async def test_project_bind_requires_manager_role(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    project = await _make_project(client, hm)
    url = f"/api/projects/{project['id']}/client"
    # обычный пользователь не может
    h = await _headers(client, logins, "other")
    resp = await client.patch(url, json={"client_id": ids["ca"]}, headers=h)
    assert resp.status_code == 403
    # admin, не являющийся владельцем проекта, может
    ha = await _headers(client, logins, "a_admin")
    resp = await client.patch(url, json={"client_id": ids["ca"]}, headers=ha)
    assert resp.status_code == 200 and resp.json()["client_id"] == ids["ca"]


async def test_other_manager_can_bind_not_his_project(client, world):
    maker, ids, logins = world
    async with maker() as s:  # второй менеджер в компании A
        s.add(_user("a_manager2", ids["a"], "manager"))
        await s.commit()
        mgr2_login = (await s.execute(select(UserModel).where(UserModel.username == "a_manager2"))).scalar_one().login
    hm = await _headers(client, logins, "a_manager")
    project = await _make_project(client, hm)  # владелец — a_manager
    resp = await client.post("/auth/login", json={"username": mgr2_login, "password": PASSWORD})
    h2 = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    resp = await client.patch(f"/api/projects/{project['id']}/client", json={"client_id": ids["ca"]}, headers=h2)
    assert resp.status_code == 200 and resp.json()["client_id"] == ids["ca"]


async def test_owner_who_lost_manager_role_cannot_bind(client, world):
    maker, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    project = await _make_project(client, hm)
    async with maker() as s:  # владельца понизили до обычного пользователя
        row = (await s.execute(select(UserModel).where(UserModel.id == ids["a_manager"]))).scalar_one()
        row.role = "user"
        await s.commit()
    resp = await client.patch(f"/api/projects/{project['id']}/client", json={"client_id": ids["ca"]}, headers=hm)
    assert resp.status_code == 403
