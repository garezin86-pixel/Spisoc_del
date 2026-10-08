# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_interactions.py
"""Этап 2 lite-CRM: взаимодействия с клиентом.

Ключевые правила: процессные поля (type, occurred_at) после создания меняют только admin/manager,
справочные (summary, contact_id) — ещё автор и ответственный; изоляция компаний; «последний контакт».
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select

from src.models.audit import AuditAction, AuditLog
from src.models.client import ClientModel
from src.models.interaction import InteractionModel
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


def _iso(delta_days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=delta_days)).isoformat()


async def _create(client, headers, client_id, **payload):
    payload.setdefault("type", "call")
    return await client.post(f"/api/clients/{client_id}/interactions", json=payload, headers=headers)


# ── создание ─────────────────────────────────────────────────────────────────
async def test_owner_creates_and_becomes_author(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "owner")
    resp = await _create(client, h, ids["ca"], type="meeting", summary="  Обсудили КП  ", occurred_at=_iso(1))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["author_id"] == ids["owner"] and body["summary"] == "Обсудили КП" and body["type"] == "meeting"


async def test_default_date_is_now(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    body = (await _create(client, h, ids["ca"], type="note")).json()
    got = datetime.fromisoformat(body["occurred_at"].replace("Z", "+00:00"))
    if got.tzinfo is None:
        got = got.replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - got).total_seconds()) < 60


async def test_non_owner_plain_user_cannot_create(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "other")
    assert (await _create(client, h, ids["ca"])).status_code == 403


async def test_validation(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    assert (await _create(client, h, ids["ca"], occurred_at=future)).status_code == 422
    assert (await _create(client, h, ids["ca"], type="telepathy")).status_code == 422
    resp = await client.post(f"/api/clients/{ids['ca']}/interactions", json={}, headers=h)
    assert resp.status_code == 422


async def test_contact_must_belong_to_same_client(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    other = (await client.post("/api/clients", json={"name": "Другой"}, headers=h)).json()
    foreign_contact = (await client.post(f"/api/clients/{other['id']}/contacts", json={"name": "Ян"}, headers=h)).json()
    own_contact = (await client.post(f"/api/clients/{ids['ca']}/contacts", json={"name": "Ира"}, headers=h)).json()

    assert (await _create(client, h, ids["ca"], contact_id=foreign_contact["id"])).status_code == 404
    assert (await _create(client, h, ids["ca"], contact_id=own_contact["id"])).status_code == 201


# ── изоляция компаний ────────────────────────────────────────────────────────
async def test_foreign_company_gets_404_everywhere(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    iid = (await _create(client, ha, ids["ca"])).json()["id"]

    hb = await _headers(client, logins, "b_admin")
    base = f"/api/clients/{ids['ca']}/interactions"
    assert (await client.get(base, headers=hb)).status_code == 404
    assert (await _create(client, hb, ids["ca"])).status_code == 404
    assert (await client.patch(f"{base}/{iid}", json={"summary": "взлом"}, headers=hb)).status_code == 404
    assert (await client.delete(f"{base}/{iid}", headers=hb)).status_code == 404
    # и через «свой» client_id чужая запись не достаётся
    own = f"/api/clients/{ids['cb']}/interactions/{iid}"
    assert (await client.patch(own, json={"summary": "взлом"}, headers=hb)).status_code == 404
    assert (await client.delete(own, headers=hb)).status_code == 404


async def test_interaction_of_other_client_not_reachable_via_wrong_client_id(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    other = (await client.post("/api/clients", json={"name": "Второй"}, headers=h)).json()
    iid = (await _create(client, h, ids["ca"])).json()["id"]
    resp = await client.patch(f"/api/clients/{other['id']}/interactions/{iid}", json={"summary": "x"}, headers=h)
    assert resp.status_code == 404


# ── список ───────────────────────────────────────────────────────────────────
async def test_list_newest_first_and_paginated(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    for days, text in [(5, "старое"), (1, "новое"), (3, "среднее")]:
        await _create(client, h, ids["ca"], summary=text, occurred_at=_iso(days))
    body = (await client.get(f"/api/clients/{ids['ca']}/interactions", headers=h)).json()
    assert [i["summary"] for i in body["items"]] == ["новое", "среднее", "старое"]
    page = (await client.get(f"/api/clients/{ids['ca']}/interactions", params={"page": 2, "size": 2}, headers=h)).json()
    assert page["total"] == 3 and len(page["items"]) == 1


async def test_any_company_member_can_read(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_manager")
    await _create(client, ha, ids["ca"])
    h = await _headers(client, logins, "other")
    resp = await client.get(f"/api/clients/{ids['ca']}/interactions", headers=h)
    assert resp.status_code == 200 and resp.json()["total"] == 1


# ── справочные и процессные поля ─────────────────────────────────────────────
async def test_author_edits_reference_fields_but_not_process_fields(client, world):
    maker, ids, logins = world
    h_owner = await _headers(client, logins, "owner")
    item = (await _create(client, h_owner, ids["ca"], type="call", occurred_at=_iso(2))).json()
    url = f"/api/clients/{ids['ca']}/interactions/{item['id']}"

    resp = await client.patch(url, json={"summary": "Уточнил детали"}, headers=h_owner)
    assert resp.status_code == 200 and resp.json()["summary"] == "Уточнил детали"

    # процессные поля: автор не может, даже будучи ответственным
    assert (await client.patch(url, json={"type": "meeting"}, headers=h_owner)).status_code == 403
    assert (await client.patch(url, json={"occurred_at": _iso(1)}, headers=h_owner)).status_code == 403
    # то же значение, что уже есть, — не изменение
    assert (await client.patch(url, json={"type": "call", "summary": "ок"}, headers=h_owner)).status_code == 200
    assert (await client.patch(url, json={"occurred_at": item["occurred_at"]}, headers=h_owner)).status_code == 200


async def test_manager_changes_process_fields_and_it_is_audited(client, world):
    maker, ids, logins = world
    h_owner = await _headers(client, logins, "owner")
    item = (await _create(client, h_owner, ids["ca"], type="call")).json()
    hm = await _headers(client, logins, "a_manager")
    url = f"/api/clients/{ids['ca']}/interactions/{item['id']}"
    resp = await client.patch(url, json={"type": "meeting"}, headers=hm)
    assert resp.status_code == 200 and resp.json()["type"] == "meeting"

    async with maker() as s:
        rows = (
            (
                await s.execute(
                    select(AuditLog).where(
                        and_(
                            AuditLog.entity_type == "interactions",
                            AuditLog.entity_id == item["id"],
                            AuditLog.action == AuditAction.update,
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].old_values == {"type": "call"} and rows[0].new_values == {"type": "meeting"}
    assert rows[0].workspace_id == ids["a"] and rows[0].user_id == ids["a_manager"]


async def test_unrelated_user_cannot_edit(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    item = (await _create(client, hm, ids["ca"])).json()  # автор — менеджер, ответственный за клиента — owner
    h = await _headers(client, logins, "other")
    url = f"/api/clients/{ids['ca']}/interactions/{item['id']}"
    assert (await client.patch(url, json={"summary": "x"}, headers=h)).status_code == 403
    # ответственный за клиента, но не автор — правит справочные поля
    ho = await _headers(client, logins, "owner")
    assert (await client.patch(url, json={"summary": "от ответственного"}, headers=ho)).status_code == 200


async def test_patch_cannot_null_process_fields(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    item = (await _create(client, h, ids["ca"])).json()
    url = f"/api/clients/{ids['ca']}/interactions/{item['id']}"
    assert (await client.patch(url, json={"type": None}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"occurred_at": None}, headers=h)).status_code == 422
    cleared = await client.patch(url, json={"summary": None}, headers=h)
    assert cleared.status_code == 200 and cleared.json()["summary"] is None


# ── удаление и «последний контакт» ───────────────────────────────────────────
async def test_only_manager_deletes(client, world):
    _, ids, logins = world
    ho = await _headers(client, logins, "owner")
    item = (await _create(client, ho, ids["ca"])).json()
    url = f"/api/clients/{ids['ca']}/interactions/{item['id']}"
    assert (await client.delete(url, headers=ho)).status_code == 403  # даже автор и ответственный
    hm = await _headers(client, logins, "a_manager")
    assert (await client.delete(url, headers=hm)).status_code == 200
    assert (await client.get(f"/api/clients/{ids['ca']}/interactions", headers=hm)).json()["total"] == 0
    assert (await client.delete(url, headers=hm)).status_code == 404


async def test_last_interaction_at_in_client_card(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    card = (await client.get(f"/api/clients/{ids['ca']}", headers=h)).json()
    assert card["last_interaction_at"] is None

    old = (await _create(client, h, ids["ca"], occurred_at=_iso(5))).json()
    new = (await _create(client, h, ids["ca"], occurred_at=_iso(1))).json()
    card = (await client.get(f"/api/clients/{ids['ca']}", headers=h)).json()
    assert card["last_interaction_at"].startswith(new["occurred_at"][:16])

    await client.delete(f"/api/clients/{ids['ca']}/interactions/{new['id']}", headers=h)
    card = (await client.get(f"/api/clients/{ids['ca']}", headers=h)).json()
    assert card["last_interaction_at"].startswith(old["occurred_at"][:16])
    # в списке клиентов поля нет — только в карточке
    listed = (await client.get("/api/clients", headers=h)).json()["items"][0]
    assert "last_interaction_at" not in listed


async def test_deleting_client_soft_deletes_interactions(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    await _create(client, h, ids["ca"])
    await _create(client, h, ids["ca"], type="email")
    assert (await client.delete(f"/api/clients/{ids['ca']}", headers=h)).status_code == 200
    assert (await client.get(f"/api/clients/{ids['ca']}/interactions", headers=h)).status_code == 404
    async with maker() as s:
        rows = (
            (await s.execute(select(InteractionModel).where(InteractionModel.client_id == ids["ca"]))).scalars().all()
        )
        assert len(rows) == 2 and all(r.deleted_at is not None for r in rows)
        client_row = (await s.execute(select(ClientModel).where(ClientModel.id == ids["ca"]))).scalar_one()
        assert client_row.deleted_at is not None
