# src/services/project_service.py
import structlog
from src.repositories.project_repository import ProjectRepository
from src.repositories.users_repository import UserRepository
from src.models.project import ProjectModel
from src.models.user import UserModel, UserRole
from src.schemas.schemas_project import ProjectCreate, ProjectUpdate
from fastapi import HTTPException

logger = structlog.get_logger()


class ProjectService:
    """Сервис управления проектами.

    Правила доступа:
    - Создавать проекты могут admin и manager.
    - Видят проект: owner, members, исполнители задач проекта, admin/manager.
    - Редактировать/удалять: owner или admin.
    - Управлять участниками: owner, admin, manager.
    """

    def __init__(self, project_repo: ProjectRepository, user_repo: UserRepository):
        self.project_repo = project_repo
        self.user_repo = user_repo

    def _require_manager(self, user: UserModel) -> None:
        if user.role not in (UserRole.admin, UserRole.manager):
            raise HTTPException(403, "Требуется роль admin или manager")

    def _require_owner_or_admin(self, project: ProjectModel, user: UserModel) -> None:
        if user.role == UserRole.admin:
            return
        if project.owner_id != user.id:
            raise HTTPException(
                403, "Только владелец или admin может выполнить это действие"
            )

    async def create_project(
        self, data: ProjectCreate, current_user: UserModel
    ) -> ProjectModel:
        """Создаёт проект. Владельцем становится текущий пользователь."""
        self._require_manager(current_user)
        project = ProjectModel(
            name=data.name,
            description=data.description,
            owner_id=current_user.id,
        )
        created = await self.project_repo.create(project)
        await logger.ainfo(
            "project_created", project_id=created.id, owner_id=current_user.id
        )
        return created

    async def get_projects(
        self, current_user: UserModel, offset: int, limit: int
    ) -> tuple[list[ProjectModel], int]:
        """Возвращает проекты доступные пользователю."""
        is_admin = current_user.role in (UserRole.admin, UserRole.manager)
        return await self.project_repo.get_all_for_user(
            user_id=current_user.id,
            is_admin=is_admin,
            offset=offset,
            limit=limit,
        )

    async def get_project(
        self, project_id: int, current_user: UserModel
    ) -> ProjectModel:
        """Возвращает проект с проверкой доступа."""
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(404, "Проект не найден")
        # Admin/manager видят всё
        if current_user.role in (UserRole.admin, UserRole.manager):
            return project
        # Проверяем что пользователь owner, member или executor
        is_visible = await self.project_repo.is_member_or_owner(
            project_id, current_user.id
        )
        executor_ids = {t.user_id for t in project.tasks if t.user_id}
        if not is_visible and current_user.id not in executor_ids:
            raise HTTPException(403, "Нет доступа к проекту")
        return project

    async def update_project(
        self, project_id: int, data: ProjectUpdate, current_user: UserModel
    ) -> ProjectModel:
        """Обновляет название и/или описание проекта."""
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(404, "Проект не найден")
        self._require_owner_or_admin(project, current_user)

        if data.name is not None:
            project.name = data.name
        if data.description is not None:
            project.description = data.description

        updated = await self.project_repo.update(project)
        await logger.ainfo("project_updated", project_id=project_id)
        return updated

    async def delete_project(self, project_id: int, current_user: UserModel) -> dict:
        """Удаляет проект вместе со всеми задачами (cascade)."""
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(404, "Проект не найден")
        self._require_owner_or_admin(project, current_user)

        await self.project_repo.delete(project)
        await logger.ainfo(
            "project_deleted", project_id=project_id, user_id=current_user.id
        )
        return {"message": f"Project {project_id} deleted"}

    async def add_member(
        self, project_id: int, user_id: int, current_user: UserModel
    ) -> dict:
        """Добавляет участника в проект."""
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(404, "Проект не найден")
        self._require_manager(current_user)
        if (
            current_user.role not in (UserRole.admin,)
            and project.owner_id != current_user.id
        ):
            # manager может добавлять только в свои проекты
            if (
                current_user.role == UserRole.manager
                and project.owner_id != current_user.id
            ):
                raise HTTPException(
                    403, "Manager может управлять только своими проектами"
                )

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(404, "Пользователь не найден")

        if any(m.id == user_id for m in project.members):
            return {"message": "Пользователь уже в проекте"}

        project.members.append(user)
        await self.project_repo.update(project)
        await logger.ainfo(
            "project_member_added", project_id=project_id, user_id=user_id
        )
        return {"message": f"User {user_id} added to project {project_id}"}

    async def remove_member(
        self, project_id: int, user_id: int, current_user: UserModel
    ) -> dict:
        """Удаляет участника из проекта."""
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(404, "Проект не найден")
        self._require_owner_or_admin(project, current_user)

        project.members = [m for m in project.members if m.id != user_id]
        await self.project_repo.update(project)
        await logger.ainfo(
            "project_member_removed", project_id=project_id, user_id=user_id
        )
        return {"message": f"User {user_id} removed from project {project_id}"}
