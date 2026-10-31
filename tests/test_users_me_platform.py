# ruff: noqa: F811  (фикстура world импортируется из test_clients и подставляется по имени аргумента)
# tests/test_users_me_platform.py
"""GET /users/me отдаёт признак админа платформы — по нему интерфейс решает, показывать ли ссылку «Админка»."""

from src.models.user import UserModel
from tests.test_clients import _headers, world  # noqa: F401  (world — фикстура)


async def test_me_exposes_is_platform_admin(client, world):
    maker, ids, logins = world
    h_admin = await _headers(client, logins, "a_admin")

    # админ компании (role=admin) — не админ платформы
    me = (await client.get("/api/users/me", headers=h_admin)).json()
    assert me["role"] == "admin"
    assert me["is_platform_admin"] is False

    # флаг выставляется только вручную в БД — после этого /users/me его показывает
    async with maker() as s:
        user = await s.get(UserModel, ids["a_admin"])
        user.is_platform_admin = True
        await s.commit()
    me = (await client.get("/api/users/me", headers=h_admin)).json()
    assert me["is_platform_admin"] is True

    # обычному сотруднику признак не выдаётся
    other = (await client.get("/api/users/me", headers=await _headers(client, logins, "owner"))).json()
    assert other["is_platform_admin"] is False


async def test_platform_flag_not_in_user_list(client, world):
    """В списке сотрудников признак админа платформы не светится — только в собственном профиле."""
    _, _, logins = world
    h = await _headers(client, logins, "a_admin")
    items = (await client.get("/api/users", headers=h)).json()["items"]
    assert items and all("is_platform_admin" not in u for u in items)
