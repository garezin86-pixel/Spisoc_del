# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_dashboard.py
"""Этап 4 lite-CRM: дашборд «что делать сегодня».

Секции: задачи на сегодня, просроченные, клиенты без контакта, ближайшие события, воронка. Чужой дашборд — только
admin/manager; изоляция компаний; «сегодня» считается в часовом поясе запроса.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.models.client import ClientModel
from src.models.enums import TaskStatus
from src.models.interaction import InteractionModel
from src.models.task import SpisokModel
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start() -> datetime:
    return _now().replace(hour=0, minute=0, second=0, microsecond=0)


async def _add(maker, *objects):
    async with maker() as s:
        s.add_all(objects)
        await s.commit()


async def _dash(client, headers, **params):
    resp = await client.get("/api/dashboard", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _task(ids, title, deadline, user="owner", **kwargs):
    return SpisokModel(
        title=title, author_id=ids["a_admin"], user_id=ids[user], deadline=deadline, workspace_id=ids["a"], **kwargs
    )


# ── структура ────────────────────────────────────────────────────────────────
async def test_empty_dashboard_structure(client, world):
    _, ids, logins = world
    body = await _dash(client, await _headers(client, logins, "owner"))
    assert body["user_id"] == ids["owner"] and body["tz"] == "UTC" and body["stale_days"] == 14
    for section in ("tasks_today", "overdue_tasks", "stale_clients", "upcoming_events"):
        assert body[section] == {"total": 0, "items": []}
    assert body["pipeline"]["stages"]


async def test_requires_auth(client, world):
    assert (await client.get("/api/dashboard")).status_code in (401, 403)


# ── задачи ───────────────────────────────────────────────────────────────────
async def test_tasks_today_and_overdue(client, world):
    maker, ids, logins = world
    start = _day_start()
    await _add(
        maker,
        _task(ids, "сегодня", start + timedelta(hours=1)),
        _task(ids, "вчера", start - timedelta(hours=1)),
        _task(ids, "завтра", start + timedelta(days=1, hours=1)),
        _task(ids, "без срока", None),
        _task(ids, "готово вчера", start - timedelta(hours=2), status=TaskStatus.done),
        _task(ids, "чужая", start + timedelta(hours=2), user="other"),
    )
    body = await _dash(client, await _headers(client, logins, "owner"))
    assert [t["title"] for t in body["tasks_today"]["items"]] == ["сегодня"]
    assert [t["title"] for t in body["overdue_tasks"]["items"]] == ["вчера"]
    assert body["tasks_today"]["total"] == 1 and body["overdue_tasks"]["total"] == 1


async def test_overdue_sorted_oldest_first_and_limited(client, world):
    maker, ids, logins = world
    start = _day_start()
    await _add(maker, *[_task(ids, f"t{i}", start - timedelta(hours=i + 1)) for i in range(25)])
    body = (await _dash(client, await _headers(client, logins, "owner")))["overdue_tasks"]
    assert body["total"] == 25 and len(body["items"]) == 20
    assert body["items"][0]["title"] == "t24"  # самая давняя


async def test_timezone_shifts_today(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    zone = "Pacific/Kiritimati"
    body = await _dash(client, h, tz=zone)
    assert body["today"] == _now().astimezone(ZoneInfo(zone)).date().isoformat()
    assert (await client.get("/api/dashboard", params={"tz": "Mars/Base"}, headers=h)).status_code == 422


async def test_param_validation(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "owner")
    for params in ({"stale_days": 0}, {"stale_days": 400}, {"events_days": 0}, {"events_days": 61}):
        assert (await client.get("/api/dashboard", params=params, headers=h)).status_code == 422


# ── клиенты без контакта ─────────────────────────────────────────────────────
async def test_stale_clients(client, world):
    maker, ids, logins = world
    old = _now() - timedelta(days=40)
    fresh = ClientModel(name="Свежий", workspace_id=ids["a"], owner_id=ids["owner"])
    stale = ClientModel(name="Давний", workspace_id=ids["a"], owner_id=ids["owner"])
    never_old = ClientModel(name="Без контактов", workspace_id=ids["a"], owner_id=ids["owner"], created_at=old)
    foreign = ClientModel(name="Чужой", workspace_id=ids["a"], owner_id=ids["other"], created_at=old)
    await _add(maker, fresh, stale, never_old, foreign)
    await _add(
        maker,
        InteractionModel(
            client_id=fresh.id, type="call", occurred_at=_now() - timedelta(days=2), workspace_id=ids["a"]
        ),
        InteractionModel(
            client_id=stale.id, type="call", occurred_at=_now() - timedelta(days=30), workspace_id=ids["a"]
        ),
        InteractionModel(
            client_id=stale.id, type="note", occurred_at=_now() - timedelta(days=45), workspace_id=ids["a"]
        ),
    )
    # ca (Ромашка, ответственный owner) создан только что и без контактов — не в списке
    body = (await _dash(client, await _headers(client, logins, "owner")))["stale_clients"]
    assert [c["name"] for c in body["items"]] == ["Без контактов", "Давний"]
    never, last = body["items"]
    assert never["last_contact_at"] is None and never["days_since_contact"] == 40
    assert last["days_since_contact"] == 30  # считается от самого свежего контакта

    narrow = (await _dash(client, await _headers(client, logins, "owner"), stale_days=35))["stale_clients"]
    assert [c["name"] for c in narrow["items"]] == ["Без контактов"]


async def test_deleted_interaction_does_not_count_as_contact(client, world):
    maker, ids, logins = world
    c = ClientModel(name="К", workspace_id=ids["a"], owner_id=ids["owner"], created_at=_now() - timedelta(days=60))
    await _add(maker, c)
    await _add(
        maker,
        InteractionModel(
            client_id=c.id,
            type="call",
            occurred_at=_now() - timedelta(days=1),
            workspace_id=ids["a"],
            deleted_at=_now(),
        ),
    )
    body = (await _dash(client, await _headers(client, logins, "owner")))["stale_clients"]
    assert [x["name"] for x in body["items"]] == ["К"]


# ── ближайшие события ────────────────────────────────────────────────────────
async def _event(client, headers, client_id, days, **payload):
    payload.setdefault("type", "meeting")
    payload["starts_at"] = (_now() + timedelta(days=days)).isoformat()
    resp = await client.post(f"/api/clients/{client_id}/events", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_upcoming_events(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    soon = await _event(client, hm, ids["ca"], 1, assignee_id=ids["owner"], title="Демо")
    later = await _event(client, hm, ids["ca"], 3, assignee_id=ids["owner"], type="call")
    await _event(client, hm, ids["ca"], 20, assignee_id=ids["owner"])  # за горизонтом
    await _event(client, hm, ids["ca"], -1, assignee_id=ids["owner"])  # уже прошло
    await _event(client, hm, ids["ca"], 1, assignee_id=ids["other"])  # чужое
    gone = await _event(client, hm, ids["ca"], 2, assignee_id=ids["owner"])
    await client.patch(f"/api/events/{gone['id']}", json={"status": "cancelled"}, headers=hm)

    ho = await _headers(client, logins, "owner")
    body = (await _dash(client, ho))["upcoming_events"]
    assert [e["id"] for e in body["items"]] == [soon["id"], later["id"]]
    assert body["items"][0]["client_name"] == "Ромашка" and body["items"][0]["title"] == "Демо"
    wide = (await _dash(client, ho, events_days=30))["upcoming_events"]
    assert wide["total"] == 3


# ── воронка ──────────────────────────────────────────────────────────────────
async def test_pipeline_counts_only_target_users_deals(client, world):
    _, ids, logins = world
    hm = await _headers(client, logins, "a_manager")
    for owner, amount in (("owner", 1000), ("owner", 500), ("other", 7)):
        resp = await client.post(
            f"/api/clients/{ids['ca']}/deals",
            json={"title": "Сделка", "amount": amount, "currency": "USD", "owner_id": ids[owner]},
            headers=hm,
        )
        assert resp.status_code == 201, resp.text

    stages = (await _dash(client, await _headers(client, logins, "owner")))["pipeline"]["stages"]
    assert sum(s["count"] for s in stages) == 2
    usd = [t for s in stages for t in s["totals"] if t["currency"] == "USD"]
    assert sum(t["count"] for t in usd) == 2 and sum(float(t["amount"]) for t in usd) == 1500


# ── права и изоляция ─────────────────────────────────────────────────────────
async def test_foreign_dashboard_permissions(client, world):
    _, ids, logins = world
    owner_view = await client.get(
        "/api/dashboard", params={"user_id": ids["owner"]}, headers=await _headers(client, logins, "other")
    )
    assert owner_view.status_code == 403

    hm = await _headers(client, logins, "a_manager")
    ok = await _dash(client, hm, user_id=ids["owner"])
    assert ok["user_id"] == ids["owner"]
    own = await client.get(
        "/api/dashboard", params={"user_id": ids["other"]}, headers=await _headers(client, logins, "other")
    )
    assert own.status_code == 200
    assert (await client.get("/api/dashboard", params={"user_id": 999999}, headers=hm)).status_code == 404
    assert (await client.get("/api/dashboard", params={"user_id": ids["b_admin"]}, headers=hm)).status_code == 404


async def test_companies_are_isolated(client, world):
    maker, ids, logins = world
    await _add(maker, _task(ids, "A-задача", _day_start() + timedelta(hours=1)))
    hb = await _headers(client, logins, "b_admin")
    body = await _dash(client, hb)
    assert body["tasks_today"]["total"] == 0 and body["stale_clients"]["total"] == 0
    assert (await client.get("/api/dashboard", params={"user_id": ids["owner"]}, headers=hb)).status_code == 404
