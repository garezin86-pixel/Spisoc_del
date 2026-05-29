from src.models.task import SpisokModel
from src.models.user import UserModel, UserRole
from src.repositories.abstract import AbstractGroupRepository


async def can_edit_task(
    task: SpisokModel,
    user: UserModel,
    group_repo: AbstractGroupRepository | None = None,
) -> bool:
    # admin и manager могут редактировать любую задачу
    if user.role in (UserRole.admin, UserRole.manager):
        return True
    # автор задачи
    if task.author_id == user.id:
        return True
    # исполнитель
    if task.user_id == user.id:
        return True
    # член группы, которой назначена задача
    if task.group_id and group_repo is not None:
        users = await group_repo.get_group_users(task.group_id)
        if any(u.id == user.id for u in users):
            return True
    return False


async def can_update_task_deadline(
    task: SpisokModel,
    user: UserModel,
) -> bool:
    # admin и manager могут менять дедлайн
    if user.role in (UserRole.admin, UserRole.manager):
        return True
    # автор задачи
    if task.author_id == user.id:
        return True
    return False


def can_delete_task(task: SpisokModel, user: UserModel) -> bool:
    """Удалять может автор, admin или manager."""
    if user.role in (UserRole.admin, UserRole.manager):
        return True
    return task.author_id == user.id


def can_reassign_task(task: SpisokModel, user: UserModel) -> bool:
    """Переназначать может автор, admin или manager."""
    if user.role in (UserRole.admin, UserRole.manager):
        return True
    return task.author_id == user.id
