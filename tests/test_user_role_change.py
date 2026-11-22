"""
Смена роли участника из веба: PATCH /users/{id}/role.

Правила (см. UserService.change_role): только admin своей компании, только
участники той же компании, нельзя понизить единственного админа, запись в audit_log.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.audit import AuditLog
from src.models.user import UserModel
from src.models.workspace import WorkspaceModel
from src.repositories.mock_repositories import MockUserRepository
from src.services.user_service import UserService
from tests.conftest import make_user


def _maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _login(client, username: str, password: str = "password123") -> None:
    resp = await client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    client.headers.update({"Authorization": f"Bearer {resp.json()['access_token']}"})


async def _role_in_db(engine, user_id: int) -> str:
    async with _maker(engine)() as s:
        return str((await s.get(UserModel, user_id)).role)


class TestChangeRoleApi:
    @pytest.mark.asyncio
    async def test_admin_promotes_user_to_manager(self, admin_client, engine):
        client, admin = admin_client
        async with _maker(engine)() as s:
            target = await make_user(s, username="to_manager")

        resp = await client.patch(f"/users/{target.id}/role", json={"role": "manager"})

        assert resp.status_code == 200
        assert resp.json()["role"] == "manager"
        assert await _role_in_db(engine, target.id) == "manager"

    @pytest.mark.asyncio
    async def test_change_is_written_to_audit_log(self, admin_client, engine):
        client, admin = admin_client
        async with _maker(engine)() as s:
            target = await make_user(s, username="audited")

        await client.patch(f"/users/{target.id}/role", json={"role": "admin"})

        async with _maker(engine)() as s:
            result = await s.execute(
                select(AuditLog).where(AuditLog.entity_type == "users", AuditLog.entity_id == target.id)
            )
            rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].user_id == admin.id
        assert rows[0].old_values == {"role": "user"}
        assert rows[0].new_values == {"role": "admin"}
        assert rows[0].workspace_id == target.workspace_id

    @pytest.mark.asyncio
    async def test_same_role_is_noop_without_audit(self, admin_client, engine):
        client, _ = admin_client
        async with _maker(engine)() as s:
            target = await make_user(s, username="same_role")

        resp = await client.patch(f"/users/{target.id}/role", json={"role": "user"})

        assert resp.status_code == 200
        async with _maker(engine)() as s:
            result = await s.execute(
                select(AuditLog).where(AuditLog.entity_id == target.id, AuditLog.entity_type == "users")
            )
            rows = result.all()
        assert rows == []

    @pytest.mark.asyncio
    async def test_regular_user_gets_403(self, auth_client, engine):
        client, me = auth_client
        async with _maker(engine)() as s:
            target = await make_user(s, username="victim_user")

        resp = await client.patch(f"/users/{target.id}/role", json={"role": "admin"})

        assert resp.status_code == 403
        assert await _role_in_db(engine, target.id) == "user"

    @pytest.mark.asyncio
    async def test_manager_gets_403(self, client, engine):
        async with _maker(engine)() as s:
            await make_user(s, username="mgr_user", role="manager")
            target = await make_user(s, username="mgr_target")
        await _login(client, "mgr_user")

        resp = await client.patch(f"/users/{target.id}/role", json={"role": "admin"})

        assert resp.status_code == 403
        assert await _role_in_db(engine, target.id) == "user"

    @pytest.mark.asyncio
    async def test_user_cannot_promote_self(self, auth_client, engine):
        client, me = auth_client

        resp = await client.patch(f"/users/{me.id}/role", json={"role": "admin"})

        assert resp.status_code == 403
        assert await _role_in_db(engine, me.id) == "user"

    @pytest.mark.asyncio
    async def test_invalid_role_returns_422(self, admin_client, engine):
        client, _ = admin_client
        async with _maker(engine)() as s:
            target = await make_user(s, username="bad_role")

        for bad in ("superuser", "ADMIN", "", None):
            resp = await client.patch(f"/users/{target.id}/role", json={"role": bad})
            assert resp.status_code == 422, bad

        assert await _role_in_db(engine, target.id) == "user"

    @pytest.mark.asyncio
    async def test_unknown_user_returns_404(self, admin_client):
        client, _ = admin_client
        resp = await client.patch("/users/999999/role", json={"role": "manager"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_unauthenticated_is_rejected(self, client):
        resp = await client.patch("/users/1/role", json={"role": "admin"})
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_cannot_demote_only_admin_even_self(self, admin_client, engine):
        client, admin = admin_client

        resp = await client.patch(f"/users/{admin.id}/role", json={"role": "user"})

        assert resp.status_code == 400
        assert await _role_in_db(engine, admin.id) == "admin"

    @pytest.mark.asyncio
    async def test_can_demote_admin_when_another_admin_exists(self, admin_client, engine):
        client, admin = admin_client
        async with _maker(engine)() as s:
            other_admin = await make_user(s, username="second_admin", role="admin")

        resp = await client.patch(f"/users/{other_admin.id}/role", json={"role": "manager"})

        assert resp.status_code == 200
        assert await _role_in_db(engine, other_admin.id) == "manager"

    @pytest.mark.asyncio
    async def test_inactive_admin_does_not_count_as_second_admin(self, admin_client, engine):
        client, admin = admin_client
        async with _maker(engine)() as s:
            await make_user(s, username="dead_admin", role="admin", is_active=False)

        resp = await client.patch(f"/users/{admin.id}/role", json={"role": "user"})

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_admin_cannot_change_role_in_another_workspace(self, admin_client, engine):
        client, _ = admin_client
        async with _maker(engine)() as s:
            other_ws = WorkspaceModel(name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
            s.add(other_ws)
            await s.commit()
            foreign = UserModel(
                username="foreign_user",
                login="foreign_user",
                password_hash="x",
                role="user",
                workspace_id=other_ws.id,
            )
            s.add(foreign)
            await s.commit()
            foreign_id = foreign.id

        resp = await client.patch(f"/users/{foreign_id}/role", json={"role": "admin"})

        assert resp.status_code == 404
        assert await _role_in_db(engine, foreign_id) == "user"

    @pytest.mark.asyncio
    async def test_role_endpoint_does_not_touch_platform_admin_flag(self, admin_client, engine):
        client, _ = admin_client
        async with _maker(engine)() as s:
            target = await make_user(s, username="no_platform")

        resp = await client.patch(f"/users/{target.id}/role", json={"role": "admin", "is_platform_admin": True})

        assert resp.status_code == 200
        async with _maker(engine)() as s:
            assert not (await s.get(UserModel, target.id)).is_platform_admin
        assert "is_platform_admin" not in resp.json()


class TestChangeRoleService:
    @pytest.mark.asyncio
    async def test_non_admin_rejected_before_any_lookup(self):
        from fastapi import HTTPException

        repo = MockUserRepository([])
        svc = UserService(repo)
        caller = UserModel(id=1, username="m", role="manager", workspace_id=1)

        with pytest.raises(HTTPException) as exc:
            await svc.change_role(2, "admin", caller)

        assert exc.value.status_code == 403
