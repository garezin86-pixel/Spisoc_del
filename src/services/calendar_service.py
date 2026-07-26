# src/services/calendar_service.py
import secrets

from src.models.user import UserModel
from src.repositories.calendar_repository import CalendarRepository
from src.utils.ics import build_ics_feed


class CalendarService:
    def __init__(self, calendar_repo: CalendarRepository):
        self.calendar_repo = calendar_repo

    async def get_or_create_token(self, user: UserModel) -> str:
        """Идемпотентно: если токен уже есть — возвращает его же, не плодит
        новые при каждом заходе на страницу настроек."""
        if user.calendar_feed_token:
            return user.calendar_feed_token
        return await self.regenerate_token(user)

    async def regenerate_token(self, user: UserModel) -> str:
        """Если ссылка утекла (например, попала в публичный скриншот) — перевыпустить без танцев с паролем/PAT."""
        token = secrets.token_urlsafe(32)
        await self.calendar_repo.set_calendar_token(user, token)
        return token

    async def build_feed_for_token(self, token: str) -> str | None:
        """Возвращает готовый .ics текст, либо None если токен не найден (эндпоинт вернёт 404)."""
        user = await self.calendar_repo.get_user_by_calendar_token(token)
        if not user:
            return None
        tasks = await self.calendar_repo.get_tasks_with_deadline_for_user(user.id)
        return build_ics_feed(tasks, calendar_name=f"Spisok Del — дедлайны ({user.username})")
