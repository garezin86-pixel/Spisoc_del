"""audit_log (лента активности и история задачи) не должен показывать события чужой компании."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.security import hash_password
from src.models import UserModel
from src.models.audit import AuditLog
from src.models.workspace import WorkspaceModel

pytestmark = pytest.mark.asyncio
PASSWORD = "password123"


@pytest.fixture(autouse=True)
def _no_background_notifications():
    with (
        patch("src.services.task_service.notify_task_assigned", new_callable=AsyncMock),
        patch("src.routers.tasks_router.notify_task_assigned", new_callable=AsyncMock),
    ):
        yield


@pytest.fixture
def maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _company(maker, name: str):
    login = f"adm_{uuid.uuid4().hex[:8]}"
    async with maker() as s:
        ws = WorkspaceModel(name=name, slug=f"co-{uuid.uuid4().hex[:6]}")
        s.add(ws)
        await s.commit()
        user = UserModel(
            username=login, login=login, password_hash=hash_password(PASSWORD), role="admin", workspace_id=ws.id
        )
        s.add(user)
        await s.commit()
        return ws.id, login, user.id


async def _headers(client, login):
    resp = await client.post("/auth/login", json={"username": login, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create_task(client, headers, title):
    resp = await client.post("/tasks/", json={"title": title}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
async def two_companies(client, maker):
    ws_a, login_a, user_a = await _company(maker, "A")
    ws_b, login_b, user_b = await _company(maker, "B")
    ha, hb = await _headers(client, login_a), await _headers(client, login_b)
    task_a = await _create_task(client, ha, "СЕКРЕТ-компании-A")
    task_b = await _create_task(client, hb, "СЕКРЕТ-компании-B")
    return dict(ws_a=ws_a, ws_b=ws_b, user_a=user_a, user_b=user_b, ha=ha, hb=hb, task_a=task_a, task_b=task_b)


async def test_activity_feed_shows_only_own_company(client, two_companies):
    c = two_companies
    for headers, own, foreign in ((c["ha"], c["task_a"], c["task_b"]), (c["hb"], c["task_b"], c["task_a"])):
        resp = await client.get("/api/analytics/activity", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        task_ids = {item["task_id"] for item in body["items"]}
        assert own in task_ids, "своя активность должна быть видна (защита от пустого теста)"
        assert foreign not in task_ids
        assert "СЕКРЕТ-компании-" + ("B" if foreign == c["task_b"] else "A") not in resp.text
        assert body["total"] == len(body["items"])  # total не считает чужие записи


async def test_activity_feed_of_foreign_user_is_empty(client, two_companies):
    c = two_companies
    resp = await client.get(f"/api/analytics/activity?user_id={c['user_b']}", headers=c["ha"])
    assert resp.status_code == 200
    assert resp.json()["items"] == [] and resp.json()["total"] == 0
    # а у своего пользователя события есть
    own = await client.get(f"/api/analytics/activity?user_id={c['user_a']}", headers=c["ha"])
    assert own.json()["total"] >= 1


async def test_task_audit_history_of_foreign_task_is_empty(client, two_companies):
    c = two_companies
    foreign = await client.get(f"/tasks/{c['task_b']}/audit", headers=c["ha"])
    assert foreign.status_code == 200 and foreign.json() == []
    own = await client.get(f"/tasks/{c['task_b']}/audit", headers=c["hb"])
    assert own.status_code == 200 and len(own.json()) >= 1  # владелец историю видит


async def test_audit_rows_carry_workspace_and_platform_session_still_sees_all(maker, two_companies):
    """Платформенная (непривязанная) сессия — SQLAdmin, фоновые задачи — по-прежнему видит записи всех компаний."""
    c = two_companies
    async with maker() as s:
        rows = (await s.scalars(select(AuditLog).where(AuditLog.entity_type == "spisok_del"))).all()
    assert {r.workspace_id for r in rows} >= {c["ws_a"], c["ws_b"]}
