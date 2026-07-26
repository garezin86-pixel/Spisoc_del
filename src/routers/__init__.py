from fastapi import APIRouter

from .analytics_router import router as analytics_router
from .attachments_router import router as attachments_router
from .auth_router import router as auth_router
from .calendar_router import router as calendar_router
from .checklist_router import router as checklist_router
from .comments_router import router as comments_router
from .group_router import router as group_router
from .pat_router import router as pat_router
from .project_router import router as project_router
from .push_router import router as push_router
from .tags_router import router as tags_router
from .tasks_router import router as tasks_router
from .templates_router import router as templates_router
from .users_router import router as users_router
from .webhook_router import router as webhook_router
from .ws_router import router as ws_router

api_router = APIRouter(prefix="/api")

api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(tasks_router)
api_router.include_router(group_router)
api_router.include_router(comments_router)
api_router.include_router(project_router)
api_router.include_router(push_router)
api_router.include_router(templates_router)
api_router.include_router(attachments_router)
api_router.include_router(checklist_router)
api_router.include_router(tags_router)
api_router.include_router(analytics_router)
api_router.include_router(calendar_router)
api_router.include_router(pat_router)
api_router.include_router(webhook_router)
api_router.include_router(ws_router)
