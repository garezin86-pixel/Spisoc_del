# src/repositories/project_repository.py
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.project import ProjectModel, project_member
from src.models.task import SpisokModel


class ProjectRepository:
    """Репозиторий проектов.

    Видимость: пользователь видит проект если он:
    - владелец проекта (owner_id == user_id)
    - участник проекта (есть в project_member)
    - исполнитель хотя бы одной задачи проекта (task.user_id == user_id)
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    def _base_query(self):
        """Базовый запрос без tasks — они не нужны при листинге проектов."""
        return select(ProjectModel).options(
            selectinload(ProjectModel.owner),
            selectinload(ProjectModel.members),
            selectinload(ProjectModel.group),
        )

    def _base_query_with_tasks(self):
        """Запрос с tasks — только для детальной карточки проекта."""
        return select(ProjectModel).options(
            selectinload(ProjectModel.owner),
            selectinload(ProjectModel.members),
            selectinload(ProjectModel.group),
            selectinload(ProjectModel.tasks).options(
                selectinload(SpisokModel.user),
                selectinload(SpisokModel.author),
            ),
        )

    def _visible_for_user(self, query, user_id: int):
        """Фильтр видимости — проект виден если пользователь owner/member/executor."""
        # Подзапрос: проекты где user является исполнителем задачи
        executor_projects = (
            select(SpisokModel.project_id)
            .where(SpisokModel.user_id == user_id)
            .where(SpisokModel.project_id.isnot(None))
            .scalar_subquery()
        )
        # Подзапрос: проекты где user является участником
        member_projects = (
            select(project_member.c.project_id).where(project_member.c.user_id == user_id).scalar_subquery()
        )
        return query.where(
            (ProjectModel.owner_id == user_id)
            | (ProjectModel.id.in_(member_projects))
            | (ProjectModel.id.in_(executor_projects))
        )

    async def get_all_for_user(
        self, user_id: int, is_admin: bool, offset: int, limit: int
    ) -> tuple[list[ProjectModel], int]:
        """Возвращает (projects, total) с учётом прав доступа."""
        query = self._base_query()
        if not is_admin:
            query = self._visible_for_user(query, user_id)

        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        projects = list((await self.session.execute(query.offset(offset).limit(limit))).scalars().all())
        return projects, total or 0

    async def get_by_id(self, project_id: int) -> ProjectModel | None:
        """Детальная карточка — грузим tasks."""
        result = await self.session.execute(self._base_query_with_tasks().where(ProjectModel.id == project_id))
        return result.scalar_one_or_none()

    async def create(self, project: ProjectModel) -> ProjectModel:
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def update(self, project: ProjectModel) -> ProjectModel:
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def delete(self, project: ProjectModel) -> None:
        await self.session.delete(project)
        await self.session.commit()

    async def is_member_or_owner(self, project_id: int, user_id: int) -> bool:
        """Проверяет что пользователь является owner или member проекта."""
        project = await self.get_by_id(project_id)
        if not project:
            return False
        if project.owner_id == user_id:
            return True
        return any(m.id == user_id for m in project.members)
