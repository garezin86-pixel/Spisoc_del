# tests/test_project_service.py
"""
Тесты для src/services/project_service.py.

Основной риск в этом сервисе — правила видимости и прав (owner/admin/manager/
member/executor). Ошибка здесь означает либо утечку чужих проектов, либо
невозможность управлять своими.
"""

import uuid

import pytest
from fastapi import HTTPException

from src.models.task import SpisokModel
from src.models.user import UserRole
from src.repositories.groups_repository import GroupRepository
from src.repositories.project_repository import ProjectRepository
from src.repositories.users_repository import UserRepository
from src.schemas.schemas_project import ProjectCreate, ProjectUpdate
from src.services.project_service import ProjectService
from tests.conftest import make_user


def build_service(session):
    return ProjectService(
        project_repo=ProjectRepository(session),
        user_repo=UserRepository(session),
        group_repo=GroupRepository(session),
    )


async def make_manager(session, **kwargs):
    user = await make_user(session, username=f"mgr_{uuid.uuid4().hex[:6]}", **kwargs)
    user.role = UserRole.manager
    await session.commit()
    await session.refresh(user)
    return user


async def make_admin(session, **kwargs):
    user = await make_user(session, username=f"adm_{uuid.uuid4().hex[:6]}", **kwargs)
    user.role = UserRole.admin
    await session.commit()
    await session.refresh(user)
    return user


async def make_plain_user(session, **kwargs):
    return await make_user(session, username=f"usr_{uuid.uuid4().hex[:6]}", **kwargs)


class TestCreateProject:
    @pytest.mark.asyncio
    async def test_manager_can_create(self, session):
        manager = await make_manager(session)
        service = build_service(session)

        project = await service.create_project(ProjectCreate(name="Новый проект"), manager)

        assert project.owner_id == manager.id
        assert project.name == "Новый проект"

    @pytest.mark.asyncio
    async def test_admin_can_create(self, session):
        admin = await make_admin(session)
        service = build_service(session)

        project = await service.create_project(ProjectCreate(name="Admin project"), admin)

        assert project.owner_id == admin.id

    @pytest.mark.asyncio
    async def test_plain_user_forbidden(self, session):
        user = await make_plain_user(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.create_project(ProjectCreate(name="X"), user)

        assert exc.value.status_code == 403


class TestGetProjects:
    @pytest.mark.asyncio
    async def test_admin_sees_all_projects(self, session):
        manager = await make_manager(session)
        admin = await make_admin(session)
        service = build_service(session)
        await service.create_project(ProjectCreate(name="Проект менеджера"), manager)

        projects, total = await service.get_projects(admin, offset=0, limit=50)

        assert total >= 1
        assert any(p.owner_id == manager.id for p in projects)

    @pytest.mark.asyncio
    async def test_plain_user_sees_only_own(self, session):
        manager = await make_manager(session)
        user = await make_plain_user(session)
        service = build_service(session)
        await service.create_project(ProjectCreate(name="Чужой проект"), manager)

        projects, total = await service.get_projects(user, offset=0, limit=50)

        assert total == 0
        assert projects == []

    @pytest.mark.asyncio
    async def test_pagination_respected(self, session):
        manager = await make_manager(session)
        service = build_service(session)
        for i in range(3):
            await service.create_project(ProjectCreate(name=f"Проект {i}"), manager)

        projects, total = await service.get_projects(manager, offset=0, limit=2)

        assert total >= 3
        assert len(projects) == 2


class TestGetProject:
    @pytest.mark.asyncio
    async def test_owner_can_view(self, session):
        manager = await make_manager(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Мой проект"), manager)

        result = await service.get_project(created.id, manager)

        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_stranger_forbidden(self, session):
        manager = await make_manager(session)
        stranger = await make_plain_user(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Чужой"), manager)

        with pytest.raises(HTTPException) as exc:
            await service.get_project(created.id, stranger)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_view_any_project(self, session):
        manager = await make_manager(session)
        admin = await make_admin(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект менеджера"), manager)

        result = await service.get_project(created.id, admin)

        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_executor_of_project_task_can_view(self, session):
        manager = await make_manager(session)
        executor = await make_plain_user(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="С задачей"), manager)

        task = SpisokModel(title="Задача проекта", author_id=manager.id, user_id=executor.id, project_id=created.id)
        session.add(task)
        await session.commit()

        # В проде create_project и get_project выполняются в РАЗНЫХ HTTP-запросах —
        # у каждого своя AsyncSession без общего identity map. Здесь же используется
        # одна session на тест, поэтому явно инвалидируем закэшированную (пустую)
        # коллекцию tasks — иначе lazy="selectin" не перечитает её повторно
        # (SQLAlchemy не обновляет уже загруженные relationship-коллекции без
        # populate_existing()), и тест ложно проверял бы не то, что происходит в проде.
        session.expire(created, ["tasks"])

        result = await service.get_project(created.id, executor)

        assert result.id == created.id

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_project(self, session):
        manager = await make_manager(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.get_project(999999, manager)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_member_can_view(self, session):
        manager = await make_manager(session)
        member = await make_plain_user(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="С участником"), manager)
        await service.add_member(created.id, member.id, manager)

        result = await service.get_project(created.id, member)

        assert result.id == created.id


class TestUpdateProject:
    @pytest.mark.asyncio
    async def test_owner_can_update(self, session):
        manager = await make_manager(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Старое имя"), manager)

        updated = await service.update_project(created.id, ProjectUpdate(name="Новое имя"), manager)

        assert updated.name == "Новое имя"

    @pytest.mark.asyncio
    async def test_admin_can_update_others_project(self, session):
        manager = await make_manager(session)
        admin = await make_admin(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект"), manager)

        updated = await service.update_project(created.id, ProjectUpdate(description="Новое описание"), admin)

        assert updated.description == "Новое описание"

    @pytest.mark.asyncio
    async def test_other_manager_forbidden(self, session):
        manager1 = await make_manager(session)
        manager2 = await make_manager(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект первого"), manager1)

        with pytest.raises(HTTPException) as exc:
            await service.update_project(created.id, ProjectUpdate(name="Захват"), manager2)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent(self, session):
        manager = await make_manager(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.update_project(999999, ProjectUpdate(name="X"), manager)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_partial_update_keeps_other_fields(self, session):
        manager = await make_manager(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Имя", description="Описание"), manager)

        updated = await service.update_project(created.id, ProjectUpdate(name="Новое имя"), manager)

        assert updated.name == "Новое имя"
        assert updated.description == "Описание"


class TestDeleteProject:
    @pytest.mark.asyncio
    async def test_owner_can_delete(self, session):
        manager = await make_manager(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="К удалению"), manager)

        result = await service.delete_project(created.id, manager)

        assert "deleted" in result["message"]
        assert await ProjectRepository(session).get_by_id(created.id) is None

    @pytest.mark.asyncio
    async def test_stranger_forbidden(self, session):
        manager = await make_manager(session)
        stranger = await make_plain_user(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Не трогай"), manager)

        with pytest.raises(HTTPException) as exc:
            await service.delete_project(created.id, stranger)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent(self, session):
        manager = await make_manager(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.delete_project(999999, manager)

        assert exc.value.status_code == 404


class TestAddMember:
    @pytest.mark.asyncio
    async def test_owner_manager_can_add_member(self, session):
        manager = await make_manager(session)
        newbie = await make_plain_user(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект"), manager)

        result = await service.add_member(created.id, newbie.id, manager)

        assert "added" in result["message"]
        refreshed = await ProjectRepository(session).get_by_id(created.id)
        assert any(m.id == newbie.id for m in refreshed.members)

    @pytest.mark.asyncio
    async def test_admin_can_add_to_any_project(self, session):
        manager = await make_manager(session)
        admin = await make_admin(session)
        newbie = await make_plain_user(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект менеджера"), manager)

        result = await service.add_member(created.id, newbie.id, admin)

        assert "added" in result["message"]

    @pytest.mark.asyncio
    async def test_other_manager_cannot_add_to_foreign_project(self, session):
        manager1 = await make_manager(session)
        manager2 = await make_manager(session)
        newbie = await make_plain_user(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект первого"), manager1)

        with pytest.raises(HTTPException) as exc:
            await service.add_member(created.id, newbie.id, manager2)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_plain_user_forbidden(self, session):
        manager = await make_manager(session)
        stranger = await make_plain_user(session)
        newbie = await make_plain_user(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект"), manager)

        with pytest.raises(HTTPException) as exc:
            await service.add_member(created.id, newbie.id, stranger)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_project(self, session):
        manager = await make_manager(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.add_member(999999, manager.id, manager)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_user(self, session):
        manager = await make_manager(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект"), manager)

        with pytest.raises(HTTPException) as exc:
            await service.add_member(created.id, 999999, manager)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_adding_existing_member_is_noop(self, session):
        manager = await make_manager(session)
        member = await make_plain_user(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект"), manager)
        await service.add_member(created.id, member.id, manager)

        result = await service.add_member(created.id, member.id, manager)

        assert "уже в проекте" in result["message"]
        refreshed = await ProjectRepository(session).get_by_id(created.id)
        assert sum(1 for m in refreshed.members if m.id == member.id) == 1


class TestRemoveMember:
    @pytest.mark.asyncio
    async def test_owner_can_remove_member(self, session):
        manager = await make_manager(session)
        member = await make_plain_user(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект"), manager)
        await service.add_member(created.id, member.id, manager)

        result = await service.remove_member(created.id, member.id, manager)

        assert "removed" in result["message"]
        refreshed = await ProjectRepository(session).get_by_id(created.id)
        assert not any(m.id == member.id for m in refreshed.members)

    @pytest.mark.asyncio
    async def test_stranger_forbidden(self, session):
        manager = await make_manager(session)
        member = await make_plain_user(session)
        stranger = await make_plain_user(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект"), manager)
        await service.add_member(created.id, member.id, manager)

        with pytest.raises(HTTPException) as exc:
            await service.remove_member(created.id, member.id, stranger)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_project(self, session):
        manager = await make_manager(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.remove_member(999999, manager.id, manager)

        assert exc.value.status_code == 404


class TestSetProjectGroup:
    @pytest.mark.asyncio
    async def test_owner_can_attach_group(self, session):
        manager = await make_manager(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект"), manager)

        from src.models.group import GroupModel

        group = GroupModel(name=f"group_{uuid.uuid4().hex[:6]}")
        session.add(group)
        await session.commit()
        await session.refresh(group)

        updated = await service.set_project_group(created.id, group.id, manager)

        assert updated.group_id == group.id

    @pytest.mark.asyncio
    async def test_can_detach_group(self, session):
        manager = await make_manager(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект"), manager)

        updated = await service.set_project_group(created.id, None, manager)

        assert updated.group_id is None

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_group(self, session):
        manager = await make_manager(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект"), manager)

        with pytest.raises(HTTPException) as exc:
            await service.set_project_group(created.id, 999999, manager)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_stranger_forbidden(self, session):
        manager = await make_manager(session)
        stranger = await make_plain_user(session)
        service = build_service(session)
        created = await service.create_project(ProjectCreate(name="Проект"), manager)

        with pytest.raises(HTTPException) as exc:
            await service.set_project_group(created.id, None, stranger)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_404_for_nonexistent_project(self, session):
        manager = await make_manager(session)
        service = build_service(session)

        with pytest.raises(HTTPException) as exc:
            await service.set_project_group(999999, None, manager)

        assert exc.value.status_code == 404
