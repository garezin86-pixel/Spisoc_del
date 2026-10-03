# src/repositories/workspace_repository.py
"""Доступ к workspace и приглашениям. Без бизнес-логики."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import UserModel
from src.models.workspace import WorkspaceModel
from src.models.workspace_invite import WorkspaceInviteModel


class WorkspaceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Приглашения ──────────────────────────────────────────────────────────
    async def get_active_invite_by_token(self, token: str) -> WorkspaceInviteModel | None:
        """Приглашение, которым можно воспользоваться прямо сейчас.

        Действующее = не отозвано, срок не истёк, компания не отключена.
        Проверка срока выполняется в SQL (а не в Python), чтобы не зависеть от
        того, вернул ли драйвер aware- или naive-datetime.
        Вызывать в сессии БЕЗ привязки к workspace — компания определяется токеном.
        """
        now = datetime.now(timezone.utc)
        return await self.session.scalar(
            select(WorkspaceInviteModel)
            .join(WorkspaceModel, WorkspaceModel.id == WorkspaceInviteModel.workspace_id)
            .where(
                WorkspaceInviteModel.token == token,
                WorkspaceInviteModel.revoked_at.is_(None),
                WorkspaceInviteModel.expires_at > now,
                WorkspaceModel.is_active.is_(True),
            )
        )

    async def create_invite(self, invite: WorkspaceInviteModel) -> WorkspaceInviteModel:
        self.session.add(invite)
        await self.session.commit()
        await self.session.refresh(invite)
        return invite

    async def list_invites(self, *, only_active: bool) -> list[WorkspaceInviteModel]:
        """Приглашения компании текущей сессии (фильтр по workspace — автоматический)."""
        stmt = select(WorkspaceInviteModel).order_by(WorkspaceInviteModel.created_at.desc())
        if only_active:
            stmt = stmt.where(
                WorkspaceInviteModel.revoked_at.is_(None),
                WorkspaceInviteModel.expires_at > datetime.now(timezone.utc),
            )
        return list((await self.session.scalars(stmt)).all())

    async def get_invite(self, invite_id: int) -> WorkspaceInviteModel | None:
        return await self.session.scalar(select(WorkspaceInviteModel).where(WorkspaceInviteModel.id == invite_id))

    async def save_invite(self, invite: WorkspaceInviteModel) -> WorkspaceInviteModel:
        await self.session.commit()
        await self.session.refresh(invite)
        return invite

    # ── Компании ─────────────────────────────────────────────────────────────
    async def slug_exists(self, slug: str) -> bool:
        return (await self.session.scalar(select(WorkspaceModel.id).where(WorkspaceModel.slug == slug))) is not None

    async def create_company(self, workspace: WorkspaceModel, admin: UserModel) -> UserModel:
        """Создаёт компанию и её первого админа ОДНОЙ транзакцией.

        Либо появляется и workspace, и пользователь, либо ничего — иначе при
        сбое на втором шаге осталась бы компания без единого сотрудника.
        """
        self.session.add(workspace)
        await self.session.flush()  # получаем workspace.id
        admin.workspace_id = workspace.id
        self.session.add(admin)
        await self.session.commit()
        await self.session.refresh(admin)
        return admin
