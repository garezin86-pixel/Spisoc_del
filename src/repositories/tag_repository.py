# src/repositories/tag_repository.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tag import TagModel


class TagRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self) -> list[TagModel]:
        result = await self.session.execute(select(TagModel).order_by(TagModel.name))
        return list(result.scalars().all())

    async def get_by_id(self, tag_id: int) -> TagModel | None:
        result = await self.session.execute(select(TagModel).where(TagModel.id == tag_id))
        return result.scalar_one_or_none()

    async def get_by_ids(self, tag_ids: list[int]) -> list[TagModel]:
        if not tag_ids:
            return []
        result = await self.session.execute(select(TagModel).where(TagModel.id.in_(tag_ids)))
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> TagModel | None:
        """
        Регистронезависимый поиск — чтобы 'Клиент' и 'клиент' считались одним тегом.

        Сравнение регистра делается в Python (str.lower()), а не через SQL
        lower(): на PostgreSQL lower() корректно сворачивает регистр Unicode
        (кириллицу в том числе), но на SQLite lower() работает только для
        ASCII. Раз тегов в команде обычно немного — полная выборка и
        сравнение в Python работает одинаково на любом бэкенде, без
        SQL-функций, чьё поведение зависит от диалекта.
        """
        all_tags = await self.get_all()
        target = name.lower()
        for tag in all_tags:
            if tag.name.lower() == target:
                return tag
        return None

    async def create(self, name: str, color: str) -> TagModel:
        tag = TagModel(name=name, color=color)
        self.session.add(tag)
        await self.session.commit()
        await self.session.refresh(tag)
        return tag

    async def get_or_create(self, name: str, color: str) -> TagModel:
        existing = await self.get_by_name(name)
        if existing:
            return existing
        return await self.create(name, color)

    async def delete(self, tag: TagModel) -> None:
        await self.session.delete(tag)
        await self.session.commit()
