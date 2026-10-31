# ruff: noqa: F811  (фикстуры world / ws / mock_reminder_bot импортируются из соседних тестов и подставляются по имени)
# tests/test_client_status.py
"""Статус клиента (active / inactive / blacklisted), последняя активность в списке и имена в истории изменений."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.models.client import ClientModel
from src.models.group import GroupModel
from src.models.interaction import InteractionModel
from src.models.project import ProjectModel
from src.services.audit_names import resolve_entity_names
from src.services.reminders.service import remind_contact_due
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)
from tests.test_contact_reminders import _client_row, _owner, ws  # noqa: F401  (ws — фикстура)
from tests.test_dashboard import _dash
from tests.test_reminders_service import mock_reminder_bot  # noqa: F401  (фикстура: бот-мок и тестовая БД)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _add(maker, *objects):
    async with maker() as s:
        s.add_all(objects)
        await s.commit()


# ── создание и изменение ─────────────────────────────────────────────────────
async def test_new_client_is_active_by_default_and_can_start_inactive(client, world):
    _, _, logins = world
    h = await _headers(client, logins, "a_manager")
    created = (await client.post("/api/clients", json={"name": "Новый"}, headers=h)).json()
    assert created["status"] == "active"
    sleeping = (await client.post("/api/clients", json={"name": "Спящий", "status": "inactive"}, headers=h)).json()
    assert sleeping["status"] == "inactive"


async def test_status_change_by_manager_and_owner(client, world):
    _, ids, logins = world
    url = f"/api/clients/{ids['ca']}"
    h_manager = await _headers(client, logins, "a_manager")
    resp = await client.patch(url, json={"status": "blacklisted"}, headers=h_manager)
    assert resp.status_code == 200 and resp.json()["status"] == "blacklisted"
    # ответственный за клиента тоже может править (статус — обычное поле карточки)
    h_owner = await _headers(client, logins, "owner")
    resp = await client.patch(url, json={"status": "active"}, headers=h_owner)
    assert resp.status_code == 200 and resp.json()["status"] == "active"
    # посторонний — нет
    h_other = await _headers(client, logins, "other")
    assert (await client.patch(url, json={"status": "inactive"}, headers=h_other)).status_code == 403


async def test_invalid_or_null_status_rejected(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    url = f"/api/clients/{ids['ca']}"
    assert (await client.patch(url, json={"status": "vip"}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"status": None}, headers=h)).status_code == 422
    assert (await client.post("/api/clients", json={"name": "X", "status": "vip"}, headers=h)).status_code == 422
    assert (await client.get("/api/clients", params={"status": "vip"}, headers=h)).status_code == 422


# ── список, фильтр и счётчики ────────────────────────────────────────────────
async def test_list_filter_by_status_and_counts(client, world):
    maker, ids, logins = world
    await _add(
        maker,
        ClientModel(name="Спящий-1", workspace_id=ids["a"], owner_id=ids["owner"], status="inactive"),
        ClientModel(
            name="Спящий-2", workspace_id=ids["a"], owner_id=ids["owner"], status="inactive", client_type="person"
        ),
        ClientModel(name="Чёрный", workspace_id=ids["a"], owner_id=ids["owner"], status="blacklisted"),
        # чужая компания не должна попадать ни в список, ни в счётчики
        ClientModel(name="Чужой спящий", workspace_id=ids["b"], owner_id=ids["b_admin"], status="inactive"),
    )
    h = await _headers(client, logins, "a_manager")

    inactive = (await client.get("/api/clients", params={"status": "inactive"}, headers=h)).json()
    assert sorted(c["name"] for c in inactive["items"]) == ["Спящий-1", "Спящий-2"]
    assert inactive["total"] == 2
    black = (await client.get("/api/clients", params={"status": "blacklisted"}, headers=h)).json()
    assert [c["name"] for c in black["items"]] == ["Чёрный"]
    everyone = (await client.get("/api/clients", headers=h)).json()
    assert everyone["total"] == 4  # Ромашка + три добавленных

    counts = (await client.get("/api/clients/status-counts", headers=h)).json()
    assert counts == {"all": 4, "active": 1, "inactive": 2, "blacklisted": 1}
    # счётчики учитывают остальные фильтры (тип клиента, поиск), но не сам статус
    people = (await client.get("/api/clients/status-counts", params={"client_type": "person"}, headers=h)).json()
    assert people == {"all": 1, "active": 0, "inactive": 1, "blacklisted": 0}
    found = (await client.get("/api/clients/status-counts", params={"search": "Чёрн"}, headers=h)).json()
    assert found == {"all": 1, "active": 0, "inactive": 0, "blacklisted": 1}


async def test_status_counts_requires_auth(client, world):
    assert (await client.get("/api/clients/status-counts")).status_code == 401


# ── последняя активность в списке ────────────────────────────────────────────
async def test_list_shows_last_interaction(client, world):
    maker, ids, logins = world
    quiet = ClientModel(name="Без контактов", workspace_id=ids["a"], owner_id=ids["owner"])
    await _add(maker, quiet)
    await _add(
        maker,
        InteractionModel(
            client_id=ids["ca"], type="note", occurred_at=_now() - timedelta(days=9), workspace_id=ids["a"]
        ),
        InteractionModel(
            client_id=ids["ca"], type="meeting", occurred_at=_now() - timedelta(days=2), workspace_id=ids["a"]
        ),
        InteractionModel(
            client_id=ids["ca"], type="call", occurred_at=_now() - timedelta(days=5), workspace_id=ids["a"]
        ),
    )
    h = await _headers(client, logins, "a_manager")
    items = {c["name"]: c for c in (await client.get("/api/clients", headers=h)).json()["items"]}
    assert items["Ромашка"]["last_interaction_type"] == "meeting"  # самое позднее по дате, а не по порядку создания
    assert items["Ромашка"]["last_interaction_at"] is not None
    assert items["Без контактов"]["last_interaction_at"] is None
    assert items["Без контактов"]["last_interaction_type"] is None


# ── экспорт ──────────────────────────────────────────────────────────────────
async def test_export_has_status_column_and_filter(client, world):
    maker, ids, logins = world
    await _add(maker, ClientModel(name="Спящий", workspace_id=ids["a"], owner_id=ids["owner"], status="inactive"))
    h = await _headers(client, logins, "a_admin")
    resp = await client.get("/api/clients/export", params={"status": "inactive"}, headers=h)
    assert resp.status_code == 200
    text = resp.content.decode("utf-8-sig")
    lines = [line for line in text.splitlines() if line]
    assert lines[0].split(";")[-1] == "Статус"
    assert len(lines) == 2 and "Спящий" in lines[1] and lines[1].split(";")[-1] == "Неактивный"


# ── побочные эффекты статуса ─────────────────────────────────────────────────
async def test_only_active_clients_count_as_stale(client, world):
    maker, ids, logins = world
    old = _now() - timedelta(days=60)
    await _add(
        maker,
        ClientModel(name="Давний активный", workspace_id=ids["a"], owner_id=ids["owner"], created_at=old),
        ClientModel(
            name="Давний спящий", workspace_id=ids["a"], owner_id=ids["owner"], created_at=old, status="inactive"
        ),
        ClientModel(
            name="Давний чёрный", workspace_id=ids["a"], owner_id=ids["owner"], created_at=old, status="blacklisted"
        ),
    )
    body = (await _dash(client, await _headers(client, logins, "owner")))["stale_clients"]
    assert [c["name"] for c in body["items"]] == ["Давний активный"]


async def test_blacklisted_client_gets_no_contact_reminder(ws, mock_reminder_bot):
    maker, w = ws
    async with maker() as s:
        owner = await _owner(s, w.id)
        await _client_row(s, w.id, owner, name="Чёрный список", status="blacklisted")
        await _client_row(s, w.id, owner, name="Обычный")
    await remind_contact_due()
    assert mock_reminder_bot.send_message.await_count == 1
    assert "Обычный" in mock_reminder_bot.send_message.await_args.kwargs["text"]


# ── имена вместо номеров в истории изменений ─────────────────────────────────
async def test_resolve_entity_names(world):
    maker, ids, _ = world
    group = GroupModel(name="Продажи", workspace_id=ids["a"])
    project = ProjectModel(name="Запуск сайта", owner_id=ids["owner"], workspace_id=ids["a"])
    await _add(maker, group, project)
    entries = [
        SimpleNamespace(
            old_values={"user_id": ids["owner"], "project_id": None},
            new_values={"user_id": str(ids["other"]), "project_id": project.id, "group_id": group.id, "title": "x"},
        ),
        SimpleNamespace(
            old_values=None, new_values={"client_id": ids["ca"], "owner_id": ids["a_manager"], "flag": True}
        ),
    ]
    async with maker() as s:
        names = await resolve_entity_names(s, entries)
    assert names["user_id"] == {ids["owner"]: "owner", ids["other"]: "other"}  # строковый id тоже понят
    assert names["project_id"] == {project.id: "Запуск сайта"}
    assert names["group_id"] == {group.id: "Продажи"}
    assert names["client_id"] == {ids["ca"]: "Ромашка"}
    assert names["owner_id"] == {ids["a_manager"]: "a_manager"}
    assert "title" not in names and "flag" not in names
