# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_project_client.py
"""Клиент в проектах: название клиента в ответе, фильтр списка по клиенту."""

from tests.test_clients import _headers, _make_project, world  # noqa: F401  (world — фикстура)


async def test_project_responses_include_client_name(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    created = await _make_project(client, h, client_id=ids["ca"])
    assert created["client_name"] == "Ромашка"

    free = await _make_project(client, h)
    assert free["client_id"] is None and free["client_name"] is None

    listed = {p["id"]: p for p in (await client.get("/api/projects", headers=h)).json()["items"]}
    assert listed[created["id"]]["client_name"] == "Ромашка"
    assert listed[free["id"]]["client_name"] is None
    detail = (await client.get(f"/api/projects/{created['id']}", headers=h)).json()
    assert detail["client_name"] == "Ромашка"

    # привязка/отвязка возвращают актуальное название
    bound = await client.patch(f"/api/projects/{free['id']}/client", json={"client_id": ids["ca"]}, headers=h)
    assert bound.json()["client_name"] == "Ромашка"
    unbound = await client.patch(f"/api/projects/{free['id']}/client", json={"client_id": None}, headers=h)
    assert unbound.json()["client_name"] is None


async def test_project_list_filtered_by_client(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    other = (await client.post("/api/clients", json={"name": "Другой клиент"}, headers=h)).json()
    mine = await _make_project(client, h, client_id=ids["ca"])
    await _make_project(client, h, client_id=other["id"])
    await _make_project(client, h)

    body = (await client.get("/api/projects", params={"client_id": ids["ca"]}, headers=h)).json()
    assert [p["id"] for p in body["items"]] == [mine["id"]]
    assert body["total"] == 1
    assert (await client.get("/api/projects", headers=h)).json()["total"] == 3


async def test_deleted_client_name_is_hidden_but_link_stays(client, world):
    _, ids, logins = world
    h = await _headers(client, logins, "a_manager")
    doomed = (await client.post("/api/clients", json={"name": "Скоро удалят"}, headers=h)).json()
    project = await _make_project(client, h, client_id=doomed["id"])
    assert project["client_name"] == "Скоро удалят"

    await client.delete(f"/api/clients/{doomed['id']}", headers=h)
    detail = (await client.get(f"/api/projects/{project['id']}", headers=h)).json()
    assert detail["client_name"] is None  # название удалённого клиента не показываем
