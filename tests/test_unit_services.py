"""
Unit-тесты сервисов — исправленные пароли (min_length=6).
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.core.security import hash_password
from src.models.task import SpisokModel, TaskStatus
from src.models.user import UserModel
from src.repositories.mock_repositories import (
    MockGroupRepository,
    MockTagRepository,
    MockTaskRepository,
    MockUserRepository,
)
from src.schemas.task import SpisokAddSchema, SpisokUpdate
from src.schemas.user import UserLogin, UserRegister
from src.services.auth_service import AuthService
from src.services.task_service import TaskService
from src.services.user_service import UserService


def make_user_model(**kwargs) -> UserModel:
    defaults = dict(
        id=1,
        username="user1",
        password_hash=hash_password("pass123"),
        role="user",
        is_active=True,
        telegram_id=None,
    )
    defaults.update(kwargs)
    user = UserModel()
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


def make_task_model(**kwargs) -> SpisokModel:
    defaults = dict(
        id=1,
        title="Task",
        is_done=False,
        author_id=1,
        user_id=None,
        group_id=None,
        deadline=None,
    )
    defaults.update(kwargs)
    task = SpisokModel()
    for k, v in defaults.items():
        setattr(task, k, v)
    return task


class TestAuthService:
    def _make_redis(self):
        r = AsyncMock()
        r.set = AsyncMock(return_value=True)
        r.get = AsyncMock(return_value=None)
        r.delete = AsyncMock(return_value=1)
        return r

    @pytest.mark.asyncio
    async def test_login_success(self):
        user = make_user_model(password_hash=hash_password("pass123"))
        service = AuthService(MockUserRepository(users=[user]), self._make_redis())
        result = await service.login(UserLogin(username="user1", password="pass123"))
        assert result.access_token is not None

    @pytest.mark.asyncio
    async def test_login_wrong_password_raises_401(self):
        user = make_user_model(password_hash=hash_password("correct123"))
        service = AuthService(MockUserRepository(users=[user]), self._make_redis())
        with pytest.raises(HTTPException) as exc:
            await service.login(UserLogin(username="user1", password="wronggg"))
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_login_user_not_found_raises_401(self):
        service = AuthService(MockUserRepository(), self._make_redis())
        with pytest.raises(HTTPException) as exc:
            await service.login(UserLogin(username="nobody", password="pass123"))
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_register_success(self):
        service = AuthService(MockUserRepository(), self._make_redis())
        result = await service.register(UserRegister(username="newuser", password="pass123"))
        assert result.username == "newuser"

    @pytest.mark.asyncio
    async def test_register_duplicate_raises_400(self):
        user = make_user_model(username="existing")
        service = AuthService(MockUserRepository(users=[user]), self._make_redis())
        with pytest.raises(HTTPException) as exc:
            await service.register(UserRegister(username="existing", password="pass123"))
        assert exc.value.status_code == 400


class FakeRedisStore:
    """Лёгкий dict-backed фейк Redis — в отличие от AsyncMock, реально хранит
    значения и умеет getdel атомарно (get+pop одной операцией), поэтому на
    нём можно честно проверить, что повторный refresh с уже использованным
    токеном действительно отклоняется, а не всегда "успешен" как с AsyncMock
    (у которого getdel() без явной настройки вернул бы truthy MagicMock)."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self._store[key] = value
        return True

    async def get(self, key):
        return self._store.get(key)

    async def delete(self, key):
        return 1 if self._store.pop(key, None) is not None else 0

    async def getdel(self, key):
        return self._store.pop(key, None)


class TestAuthServiceRefreshRotation:
    """Регресс: refresh() раньше делал redis.get() и redis.delete()
    отдельными вызовами — между ними было окно гонки, в котором два
    параллельных запроса с одним refresh-токеном оба проходили проверку
    "токен существует" и оба получали новую пару токенов. Теперь используется
    атомарный redis.getdel()."""

    @pytest.mark.asyncio
    async def test_refresh_returns_new_tokens_for_valid_token(self):
        user = make_user_model()
        redis = FakeRedisStore()
        service = AuthService(MockUserRepository(users=[user]), redis)

        login_result = await service.login(UserLogin(username="user1", password="pass123"))
        refreshed = await service.refresh(login_result.refresh_token)

        assert refreshed.access_token is not None
        assert refreshed.refresh_token is not None
        assert refreshed.refresh_token != login_result.refresh_token

    @pytest.mark.asyncio
    async def test_refresh_rejects_already_used_token(self):
        """Второй refresh тем же токеном (после того как он уже "сгорел") —
        должен получить 401, а не новую пару токенов."""
        user = make_user_model()
        redis = FakeRedisStore()
        service = AuthService(MockUserRepository(users=[user]), redis)

        login_result = await service.login(UserLogin(username="user1", password="pass123"))
        await service.refresh(login_result.refresh_token)  # первый refresh — сжигает токен

        with pytest.raises(HTTPException) as exc:
            await service.refresh(login_result.refresh_token)  # повтор тем же токеном
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_uses_atomic_getdel_not_get_then_delete(self):
        """Замок на реализацию: consume-проверка должна идти через ОДИН
        атомарный вызов getdel(), а не через раздельные get()+delete() —
        именно раздельность и создавала гонку."""
        user = make_user_model()
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.getdel = AsyncMock(return_value=str(user.id))
        service = AuthService(MockUserRepository(users=[user]), redis)

        login_result = await service.login(UserLogin(username="user1", password="pass123"))
        redis.get.reset_mock()
        redis.delete.reset_mock()

        await service.refresh(login_result.refresh_token)

        redis.getdel.assert_called_once()
        redis.get.assert_not_called()
        redis.delete.assert_not_called()


class TestUserService:
    @pytest.mark.asyncio
    async def test_create_user_as_admin_success(self):
        admin = make_user_model(role="admin")
        service = UserService(MockUserRepository())
        result = await service.create_user(UserRegister(username="newuser", password="pass1234", role="user"), admin)
        assert result.username == "newuser"

    @pytest.mark.asyncio
    async def test_create_user_as_non_admin_raises_403(self):
        user = make_user_model(role="user")
        service = UserService(MockUserRepository())
        with pytest.raises(HTTPException) as exc:
            await service.create_user(UserRegister(username="newuser", password="pass1234"), user)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_create_user_duplicate_raises_400(self):
        admin = make_user_model(role="admin")
        existing = make_user_model(id=2, username="existing")
        service = UserService(MockUserRepository(users=[existing]))
        with pytest.raises(HTTPException) as exc:
            await service.create_user(UserRegister(username="existing", password="pass1234"), admin)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_user_self_allowed(self):
        user = make_user_model(id=5)
        service = UserService(MockUserRepository(users=[user]))
        result = await service.get_user(5, user)
        assert result.id == 5

    @pytest.mark.asyncio
    async def test_get_user_other_is_visible_to_anyone(self):
        """Видимость профиля общая для команды — см. UserService.get_user."""
        user = make_user_model(id=1)
        other = make_user_model(id=2, username="other")
        service = UserService(MockUserRepository(users=[user, other]))
        result = await service.get_user(2, user)
        assert result.id == 2

    @pytest.mark.asyncio
    async def test_admin_can_see_anyone(self):
        admin = make_user_model(id=1, role="admin")
        other = make_user_model(id=99, username="someone")
        service = UserService(MockUserRepository(users=[admin, other]))
        result = await service.get_user(99, admin)
        assert result.id == 99

    @pytest.mark.asyncio
    async def test_delete_not_found_raises_404(self):
        service = UserService(MockUserRepository())
        with pytest.raises(HTTPException) as exc:
            await service.delete_user(999)
        assert exc.value.status_code == 404


class TestTaskService:
    def _make_service(self, tasks=None, users=None, groups=None):
        session = MagicMock()
        session.info = {"audit_user_id": 1}
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        return TaskService(
            task_repo=MockTaskRepository(tasks=tasks),
            user_repo=MockUserRepository(users=users),
            group_repo=MockGroupRepository(groups=groups),
            tag_repo=MockTagRepository(),
            session=session,  # теперь не None
        )

    @pytest.mark.asyncio
    async def test_add_task_success(self):
        author = make_user_model(id=1)
        service = self._make_service(users=[author])
        result = await service.add_task(SpisokAddSchema(title="New task"), author)  # type: ignore
        assert result.title == "New task"

    @pytest.mark.asyncio
    async def test_add_task_user_and_group_raises_422(self):
        """Pydantic отклоняет на уровне схемы."""
        with pytest.raises(Exception):
            SpisokAddSchema(title="T", user_id=1, group_id=2)  # type: ignore

    @pytest.mark.asyncio
    async def test_filter_tasks_forwards_is_done_to_repository(self):
        """Регресс: filter_tasks() принимал is_done, но никогда не передавал
        его в repo.get_filtered_tasks() — фильтрация по статусу done молча
        не работала бы, если её кто-то использует (например, бот)."""
        author = make_user_model(id=1)
        done_task = make_task_model(id=1, title="Done", status=TaskStatus.done, author_id=1)
        todo_task = make_task_model(id=2, title="Todo", status=TaskStatus.todo, author_id=1)
        service = self._make_service(tasks=[done_task, todo_task], users=[author])

        only_done = await service.filter_tasks(
            author, filter_user_group=None, group_id=None, filter_type=None, is_done=True, limit=50, offset=0
        )
        only_not_done = await service.filter_tasks(
            author, filter_user_group=None, group_id=None, filter_type=None, is_done=False, limit=50, offset=0
        )
        everything = await service.filter_tasks(
            author, filter_user_group=None, group_id=None, filter_type=None, is_done=None, limit=50, offset=0
        )

        assert [t.id for t in only_done] == [1]
        assert [t.id for t in only_not_done] == [2]
        assert {t.id for t in everything} == {1, 2}

    @pytest.mark.asyncio
    async def test_get_calendar_tasks_filters_by_deadline_range_and_visibility(self):
        """Регресс на баг с типизацией: AbstractTaskRepository не объявлял
        get_calendar_tasks (несмотря на то, что TaskRepository его реализует),
        из-за чего статические анализаторы (Pyright/Pylance) не видели метод
        через self.task_repo: AbstractTaskRepository. Заодно проверяет саму
        логику — диапазон дат и видимость по умолчанию (автор или исполнитель)."""
        author = make_user_model(id=1)
        other_user = make_user_model(id=2)
        in_range_mine = make_task_model(id=1, title="In range, mine", author_id=1, deadline=datetime(2030, 6, 15))
        in_range_other = make_task_model(
            id=2, title="In range, foreign", author_id=2, user_id=2, deadline=datetime(2030, 6, 20)
        )
        out_of_range = make_task_model(id=3, title="Out of range", author_id=1, deadline=datetime(2030, 7, 15))
        no_deadline = make_task_model(id=4, title="No deadline", author_id=1, deadline=None)
        service = self._make_service(
            tasks=[in_range_mine, in_range_other, out_of_range, no_deadline], users=[author, other_user]
        )

        result = await service.get_calendar_tasks(author, date_from=datetime(2030, 6, 1), date_to=datetime(2030, 7, 1))

        assert [t.id for t in result] == [1]  # только "своя" задача в диапазоне

    @pytest.mark.asyncio
    async def test_delete_by_author(self):
        author = make_user_model(id=1)
        task = make_task_model(id=1, author_id=1)
        service = self._make_service(tasks=[task])
        result = await service.delete_task(1, author)
        assert "deleted" in result["message"]

    @pytest.mark.asyncio
    async def test_delete_by_non_author_raises(self):
        other = make_user_model(id=2)
        task = make_task_model(id=1, author_id=1)
        service = self._make_service(tasks=[task])
        with pytest.raises(HTTPException) as exc:
            await service.delete_task(1, other)
        assert exc.value.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_delete_admin_can_delete_any(self):
        admin = make_user_model(id=99, role="admin")
        task = make_task_model(id=1, author_id=1)
        service = self._make_service(tasks=[task])
        result = await service.delete_task(1, admin)
        assert "deleted" in result["message"]

    @pytest.mark.asyncio
    async def test_delete_manager_can_delete_any(self):
        manager = make_user_model(id=50, role="manager")
        task = make_task_model(id=1, author_id=1)
        service = self._make_service(tasks=[task])
        result = await service.delete_task(1, manager)
        assert "deleted" in result["message"]

    @pytest.mark.asyncio
    async def test_delete_not_found_raises_404(self):
        service = self._make_service()
        with pytest.raises(HTTPException) as exc:
            await service.delete_task(999, make_user_model())
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_title(self):
        user = make_user_model(id=1)
        task = make_task_model(id=1, author_id=1)
        service = self._make_service(tasks=[task])
        result = await service.update_task(1, SpisokUpdate(title="Updated"), user)
        assert result.title == "Updated"

    @pytest.mark.asyncio
    async def test_reassign_both_raises_400(self):
        author = make_user_model(id=1)
        task = make_task_model(id=1, author_id=1)
        service = self._make_service(tasks=[task])
        with pytest.raises(HTTPException) as exc:
            await service.reassign_task(1, author, user_id=2, group_id=3)
        assert exc.value.status_code == 400


class TestPermissions:
    @pytest.mark.asyncio
    async def test_admin_can_edit(self):
        from src.services.permissions import can_edit_task

        admin = make_user_model(role="admin")
        task = make_task_model(author_id=99, user_id=99)
        assert await can_edit_task(task, admin) is True

    @pytest.mark.asyncio
    async def test_manager_can_edit(self):
        from src.services.permissions import can_edit_task

        manager = make_user_model(id=5, role="manager")
        task = make_task_model(author_id=99, user_id=99)
        assert await can_edit_task(task, manager) is True

    @pytest.mark.asyncio
    async def test_author_can_edit(self):
        from src.services.permissions import can_edit_task

        user = make_user_model(id=1)
        task = make_task_model(author_id=1)
        assert await can_edit_task(task, user) is True

    @pytest.mark.asyncio
    async def test_executor_can_edit(self):
        from src.services.permissions import can_edit_task

        user = make_user_model(id=5)
        task = make_task_model(author_id=1, user_id=5)
        assert await can_edit_task(task, user) is True

    @pytest.mark.asyncio
    async def test_stranger_cannot_edit(self):
        from src.services.permissions import can_edit_task

        stranger = make_user_model(id=99)
        task = make_task_model(author_id=1, user_id=2, group_id=None)
        assert await can_edit_task(task, stranger) is False

    @pytest.mark.asyncio
    async def test_deadline_permissions(self):
        from src.services.permissions import can_update_task_deadline

        author = make_user_model(id=1)
        manager = make_user_model(id=2, role="manager")
        admin = make_user_model(id=3, role="admin")
        executor = make_user_model(id=4)
        task = make_task_model(author_id=1)
        assert await can_update_task_deadline(task, author) is True
        assert await can_update_task_deadline(task, manager) is True
        assert await can_update_task_deadline(task, admin) is True
        assert await can_update_task_deadline(task, executor) is False

    @pytest.mark.asyncio
    async def test_can_delete(self):
        from src.services.permissions import can_delete_task

        author = make_user_model(id=1)
        manager = make_user_model(id=2, role="manager")
        admin = make_user_model(id=3, role="admin")
        other = make_user_model(id=4)
        task = make_task_model(author_id=1)
        assert can_delete_task(task, author) is True
        assert can_delete_task(task, manager) is True
        assert can_delete_task(task, admin) is True
        assert can_delete_task(task, other) is False
