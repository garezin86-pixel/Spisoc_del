# src/repositories/pat_repository.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.personal_access_token import PersonalAccessTokenModel


class PatRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_id: int,
        name: str,
        token_hash: str,
        token_prefix: str,
        expires_at: datetime | None,
    ) -> PersonalAccessTokenModel:
        pat = PersonalAccessTokenModel(
            user_id=user_id,
            name=name,
            token_hash=token_hash,
            token_prefix=token_prefix,
            expires_at=expires_at,
        )
        self.session.add(pat)
        await self.session.commit()
        await self.session.refresh(pat)
        return pat

    async def get_by_hash(self, token_hash: str) -> PersonalAccessTokenModel | None:
        result = await self.session.execute(
            select(PersonalAccessTokenModel).where(PersonalAccessTokenModel.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, pat_id: int) -> PersonalAccessTokenModel | None:
        result = await self.session.execute(
            select(PersonalAccessTokenModel).where(PersonalAccessTokenModel.id == pat_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: int) -> list[PersonalAccessTokenModel]:
        result = await self.session.execute(
            select(PersonalAccessTokenModel)
            .where(PersonalAccessTokenModel.user_id == user_id)
            .order_by(PersonalAccessTokenModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def touch_last_used(self, pat: PersonalAccessTokenModel) -> None:
        """
        Обновляет last_used_at при каждом успешном использовании токена.

        Best-effort: если commit не удался (например, БД временно недоступна),
        это не должно ронять сам API-запрос — аутентификация уже прошла успешно,
        обновление метки последнего использования не критично для текущего запроса.
        """
        pat.last_used_at = datetime.now(timezone.utc)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()

    async def delete(self, pat: PersonalAccessTokenModel) -> None:
        await self.session.delete(pat)
        await self.session.commit()
