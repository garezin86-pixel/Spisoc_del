# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_scheduled_events.py
"""Этап 4 lite-CRM: запланированные встречи и звонки.

Ключевые правила: создают admin/manager и ответственный за клиента; меняют и завершают admin/manager и ответственный
за событие; удаляет только admin/manager; complete создаёт взаимодействие и не повторяется; изоляция компаний.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.models.interaction import InteractionModel
from src.models.scheduled_event import ScheduledEventModel
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


def _iso(delta_days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).isoformat()


async def _create(client, headers, client_id, **payload):
    payload.setdefault("type", "meeting")
    payload.setdefault("starts_at", _iso(1))
    return await client.post(f"/api/clients/{client_id}/events", json=payload, headers=headers)


# ── создание ─────────────────────────────────────────────────────────────────
async def test_owner_creates_event_assigned_to_self(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "owner")
    resp = await _create(client, h, ids["ca"], title="  Демо  ", duration_minutes=45)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["assignee_id"] == ids["owner"] and body["created_by_id"] == ids["owner"]
    assert body["title"] == "Демо" and body["status"] == "planned" and body["duration_minutes"] == 45


async def test_manager_assigns_to_colleague(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    resp = await _create(client, h, ids["ca"], assignee_id=ids["other"])
    assert resp.status_code == 201 and resp.json()["assignee_id"] == ids["other"]


async def test_non_owner_plain_user_cannot_create(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "other")
    assert (await _create(client, h, ids["ca"])).status_code == 403


async def test_validation_and_missing_refs(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    assert (await _create(client, h, ids["ca"], type="email")).status_code == 422
    assert (await _create(client, h, ids["ca"], duration_minutes=0)).status_code == 422
    assert (await _create(client, h, ids["ca"], assignee_id=999999)).status_code == 404
    assert (await _create(client, h, ids["ca"], contact_id=999999)).status_code == 404
    assert (await _create(client, h, 999999)).status_code == 404


async def test_assignee_from_other_company_rejected(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    assert (await _create(client, h, ids["ca"], assignee_id=ids["b_admin"])).status_code == 404


async def test_other_company_client_is_404(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    assert (await _create(client, h, ids["cb"])).status_code == 404
    assert (await client.get(f"/api/clients/{ids['cb']}/events", headers=h)).status_code == 404


# ── чтение ───────────────────────────────────────────────────────────────────
async def test_list_sorted_and_cancelled_hidden(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    late = (await _create(client, h, ids["ca"], starts_at=_iso(5))).json()
    soon = (await _create(client, h, ids["ca"], starts_at=_iso(1))).json()
    gone = (await _create(client, h, ids["ca"], starts_at=_iso(2))).json()
    assert (await client.patch(f"/api/events/{gone['id']}", json={"status": "cancelled"}, headers=h)).status_code == 200

    items = (await client.get(f"/api/clients/{ids['ca']}/events", headers=h)).json()["items"]
    assert [i["id"] for i in items] == [soon["id"], late["id"]]
    cancelled = (await client.get(f"/api/clients/{ids['ca']}/events?status=cancelled", headers=h)).json()["items"]
    assert [i["id"] for i in cancelled] == [gone["id"]]


async def test_calendar_filters_by_period_and_assignee(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    mine = (await _create(client, h, ids["ca"], starts_at=_iso(1))).json()
    theirs = (await _create(client, h, ids["ca"], starts_at=_iso(1), assignee_id=ids["other"])).json()
    far = (await _create(client, h, ids["ca"], starts_at=_iso(30))).json()

    params = {"from": _iso(0), "to": _iso(7)}
    got = (await client.get("/api/events", params=params, headers=h)).json()["items"]
    assert {i["id"] for i in got} == {mine["id"], theirs["id"]}
    got = (await client.get("/api/events", params={**params, "assignee_id": ids["other"]}, headers=h)).json()["items"]
    assert [i["id"] for i in got] == [theirs["id"]]
    assert far["id"] not in {i["id"] for i in got}


async def test_calendar_isolated_between_companies(client, world):
    _, ids, logins = world
    ha = await _headers(client, logins, "a_admin")
    hb = await _headers(client, logins, "b_admin")
    await _create(client, ha, ids["ca"])
    assert (await client.get("/api/events", headers=hb)).json()["total"] == 0


# ── изменение ────────────────────────────────────────────────────────────────
async def test_assignee_and_manager_can_edit_others_cannot(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    event = (await _create(client, hm, ids["ca"], assignee_id=ids["other"])).json()
    url = f"/api/events/{event['id']}"

    assert (
        await client.patch(url, json={"title": "X"}, headers=await _headers(client, logins, "owner"))
    ).status_code == 403
    resp = await client.patch(
        url, json={"title": "Y", "starts_at": _iso(3)}, headers=await _headers(client, logins, "other")
    )
    assert resp.status_code == 200 and resp.json()["title"] == "Y"
    assert (await client.patch(url, json={"notes": "z"}, headers=hm)).status_code == 200


async def test_patch_validation(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    url = f"/api/events/{(await _create(client, h, ids['ca'])).json()['id']}"
    assert (await client.patch(url, json={"status": "done"}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"starts_at": None}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"assignee_id": 999999}, headers=h)).status_code == 404
    cleared = await client.patch(url, json={"title": "t"}, headers=h)
    assert (await client.patch(url, json={"title": None}, headers=h)).json()[
        "title"
    ] is None and cleared.status_code == 200


async def test_cancel_and_reopen(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    url = f"/api/events/{(await _create(client, h, ids['ca'])).json()['id']}"
    assert (await client.patch(url, json={"status": "cancelled"}, headers=h)).json()["status"] == "cancelled"
    assert (await client.patch(url, json={"status": "planned"}, headers=h)).json()["status"] == "planned"


# ── завершение ───────────────────────────────────────────────────────────────
async def test_complete_creates_interaction_now(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "owner")
    event = (await _create(client, h, ids["ca"], type="call", notes="План разговора", starts_at=_iso(-0.01))).json()
    resp = await client.post(f"/api/events/{event['id']}/complete", json={"summary": "  Договорились  "}, headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "done" and body["completed_interaction_id"]

    async with maker() as s:
        item = (
            await s.execute(select(InteractionModel).where(InteractionModel.id == body["completed_interaction_id"]))
        ).scalar_one()
    assert item.client_id == ids["ca"] and item.type == "call" and item.summary == "Договорились"
    assert item.author_id == ids["owner"]
    occurred = item.occurred_at if item.occurred_at.tzinfo else item.occurred_at.replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - occurred).total_seconds()) < 60


async def test_complete_without_body_uses_notes(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    event = (await _create(client, h, ids["ca"], notes="Повестка")).json()
    resp = await client.post(f"/api/events/{event['id']}/complete", headers=h)
    assert resp.status_code == 200, resp.text
    async with maker() as s:
        item = (
            await s.execute(
                select(InteractionModel).where(InteractionModel.id == resp.json()["completed_interaction_id"])
            )
        ).scalar_one()
    assert item.summary == "Повестка"


async def test_complete_twice_or_cancelled_conflicts(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_admin")
    done = (await _create(client, h, ids["ca"])).json()
    assert (await client.post(f"/api/events/{done['id']}/complete", json={}, headers=h)).status_code == 200
    assert (await client.post(f"/api/events/{done['id']}/complete", json={}, headers=h)).status_code == 409
    assert (await client.patch(f"/api/events/{done['id']}", json={"title": "x"}, headers=h)).status_code == 409

    cancelled = (await _create(client, h, ids["ca"])).json()
    await client.patch(f"/api/events/{cancelled['id']}", json={"status": "cancelled"}, headers=h)
    assert (await client.post(f"/api/events/{cancelled['id']}/complete", json={}, headers=h)).status_code == 409


async def test_complete_forbidden_for_stranger(client, world):
    _, ids, logins = world
    event = (await _create(client, await _headers(client, logins, "a_manager"), ids["ca"])).json()
    resp = await client.post(
        f"/api/events/{event['id']}/complete", json={}, headers=await _headers(client, logins, "other")
    )
    assert resp.status_code == 403


# ── удаление ─────────────────────────────────────────────────────────────────
async def test_only_managers_delete_softly(client, world):
    maker, ids, logins = world
    ho = await _headers(client, logins, "owner")
    event = (await _create(client, ho, ids["ca"])).json()
    url = f"/api/events/{event['id']}"

    assert (await client.delete(url, headers=ho)).status_code == 403
    assert (await client.delete(url, headers=await _headers(client, logins, "a_manager"))).status_code == 200
    assert (await client.delete(url, headers=await _headers(client, logins, "a_manager"))).status_code == 404
    async with maker() as s:
        row = (await s.execute(select(ScheduledEventModel).where(ScheduledEventModel.id == event["id"]))).scalar_one()
    assert row.deleted_at is not None
