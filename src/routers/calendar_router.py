# src/routers/calendar_router.py
from fastapi import APIRouter, Depends, Request, Response

from src.core.dependencies import get_current_user
from src.core.exceptions import not_found
from src.db import SessionDep
from src.models.user import UserModel
from src.repositories.calendar_repository import CalendarRepository
from src.schemas.calendar import CalendarFeedResponse
from src.services.calendar_service import CalendarService

router = APIRouter(prefix="/calendar", tags=["Calendar"])


def get_calendar_service(session: SessionDep) -> CalendarService:
    return CalendarService(CalendarRepository(session))


def _build_feed_url(request: Request, token: str) -> str:
    # Абсолютный URL строим из самого запроса, а не из env-переменной:
    # фронтенд и API живут на одном домене (Render отдаёт frontend/dist
    # через тот же FastAPI-процесс), так что Host запроса — всегда
    # правильный базовый адрес, без риска рассинхронизации с конфигом.
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/calendar/feed.ics?token={token}"


@router.get(
    "/token",
    response_model=CalendarFeedResponse | None,
    summary="Получить текущую ссылку на iCal-фид (если уже создавалась)",
)
async def get_calendar_token(
    request: Request,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    if not current_user.calendar_feed_token:
        return None
    return CalendarFeedResponse(feed_url=_build_feed_url(request, current_user.calendar_feed_token))


@router.post(
    "/token",
    response_model=CalendarFeedResponse,
    summary="Создать (или перевыпустить) ссылку на iCal-фид",
    description=(
        "Ссылку можно вставить как URL подписки в Google Calendar ('Другие календари' → "
        "'По URL') или Outlook ('Добавить календарь' → 'Из интернета'). Токен в URL — "
        "единственный способ аутентификации для календарных клиентов, которые сами "
        "периодически опрашивают ссылку и не умеют слать заголовок Authorization. "
        "Если ссылка попала не в те руки — вызовите ещё раз, старая сразу перестанет работать."
    ),
)
async def create_or_rotate_calendar_token(
    request: Request,
    session: SessionDep,
    current_user: UserModel = Depends(get_current_user),
):
    token = await get_calendar_service(session).regenerate_token(current_user)
    return CalendarFeedResponse(feed_url=_build_feed_url(request, token))


@router.get(
    "/feed.ics",
    summary="iCal-фид дедлайнов (без обычной авторизации — токен в query-параметре)",
    description=(
        "Аутентификация через ?token=..., а не Bearer-заголовок — так его может опрашивать Google Calendar/Outlook."
    ),
)
async def calendar_feed(token: str, session: SessionDep):
    ics_text = await get_calendar_service(session).build_feed_for_token(token)
    if ics_text is None:
        not_found("Неверная или отозванная ссылка на календарь")
    return Response(
        content=ics_text,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="spisok-del-deadlines.ics"'},
    )
