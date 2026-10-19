# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_task_client.py
"""Связь задачи с клиентом CRM (client_id): создание, правка, фильтр, отображение, повторяющиеся задачи, дашборд."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.models.task import SpisokModel
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


async def _create(client, headers, **payload):
    payload.setdefault("title", "Задача")
    return await client.post("/api/tasks", json=payload, headers=headers)


async def test_create_task_with_client(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    resp = await _create(client, h, client_id=ids["ca"])
    assert resp.status_code == 201, resp.text
    assert resp.json()["client_id"] == ids["ca"] and resp.json()["client_name"] == "Ромашка"
    plain = await _create(client, h)
    assert plain.json()["client_id"] is None and plain.json()["client_name"] is None


async def test_unknown_or_foreign_client_is_rejected(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    for bad in (999999, ids["cb"]):  # cb — клиент другой компании
        resp = await _create(client, h, client_id=bad)
        assert resp.status_code == 404 and "Клиент не найден" in resp.text
    assert (await _create(client, h, client_id=0)).status_code == 422


async def test_patch_sets_keeps_and_clears_the_client(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    task_id = (await _create(client, h)).json()["id"]
    url = f"/api/tasks/{task_id}"

    linked = await client.patch(url, json={"client_id": ids["ca"]}, headers=h)
    assert linked.status_code == 200 and linked.json()["client_name"] == "Ромашка"
    kept = await client.patch(url, json={"title": "Новое название"}, headers=h)
    assert kept.json()["client_id"] == ids["ca"]  # поле не передано — связь не трогаем

    assert (await client.patch(url, json={"client_id": ids["cb"]}, headers=h)).status_code == 404
    assert (await client.get(url, headers=h)).json()["client_id"] == ids["ca"]

    cleared = await client.patch(url, json={"client_id": None}, headers=h)
    assert cleared.status_code == 200 and cleared.json()["client_id"] is None and cleared.json()["client_name"] is None


async def test_filter_by_client(client, world):
    maker, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    mine = (await _create(client, h, title="Ромашке", client_id=ids["ca"])).json()["id"]
    await _create(client, h, title="Без клиента")
    async with maker() as s:
        from src.models.client import ClientModel

        other = ClientModel(name="Лилия", workspace_id=ids["a"], owner_id=ids["owner"])
        s.add(other)
        await s.commit()
        other_id = other.id
    await _create(client, h, title="Лилии", client_id=other_id)

    got = await client.get("/api/tasks/filter", params={"client_id": ids["ca"]}, headers=h)
    assert got.status_code == 200, got.text
    assert [t["id"] for t in got.json()["items"]] == [mine]
    assert got.json()["items"][0]["client_name"] == "Ромашка"
    assert (await client.get("/api/tasks/filter", params={"client_id": 0}, headers=h)).status_code == 422


async def test_client_filter_includes_tasks_that_live_in_projects(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    project = await client.post("/api/projects", json={"name": "Проект"}, headers=h)
    assert project.status_code == 201, project.text
    in_project = (
        await _create(client, h, title="В проекте", client_id=ids["ca"], project_id=project.json()["id"])
    ).json()
    default_list = await client.get("/api/tasks/filter", headers=h)
    assert in_project["id"] not in [t["id"] for t in default_list.json()["items"]]  # общий список проекты скрывает
    by_client = await client.get("/api/tasks/filter", params={"client_id": ids["ca"]}, headers=h)
    assert [t["id"] for t in by_client.json()["items"]] == [in_project["id"]]  # а карточке клиента нужны все


async def test_deleted_client_is_not_shown_on_the_task(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    task_id = (await _create(client, h, client_id=ids["ca"])).json()["id"]
    assert (await client.delete(f"/api/clients/{ids['ca']}", headers=h)).status_code in (200, 204)
    task = (await client.get(f"/api/tasks/{task_id}", headers=h)).json()
    assert task["client_name"] is None  # название удалённого клиента не светим


async def test_recurring_task_keeps_its_client(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    deadline = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    first = (await _create(client, h, client_id=ids["ca"], recurrence_rule="daily", deadline=deadline)).json()
    done = await client.patch(f"/api/tasks/{first['id']}", json={"status": "done"}, headers=h)
    assert done.status_code == 200, done.text
    by_client = await client.get("/api/tasks/filter", params={"client_id": ids["ca"]}, headers=h)
    items = by_client.json()["items"]
    assert len(items) == 2 and {t["status"] for t in items} == {"done", "todo"}  # следующее повторение — тоже у клиента


async def test_dashboard_task_shows_client(client, world):
    maker, ids, logins = world
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    async with maker() as s:
        s.add(
            SpisokModel(
                title="Позвонить", author_id=ids["a_admin"], user_id=ids["owner"], client_id=ids["ca"],
                deadline=start + timedelta(hours=1), workspace_id=ids["a"],
            )
        )  # fmt: skip
        await s.commit()
    body = (await client.get("/api/dashboard", headers=await _headers(client, logins, "owner"))).json()
    item = body["tasks_today"]["items"][0]
    assert (item["client_id"], item["client_name"]) == (ids["ca"], "Ромашка")
    async with maker() as s:
        assert (await s.execute(select(SpisokModel.client_id))).scalar_one() == ids["ca"]
