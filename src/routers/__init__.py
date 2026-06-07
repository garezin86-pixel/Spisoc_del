from fastapi import APIRouter

from .auth_router import router as auth_router
from .users_router import router as users_router
from .group_router import router as group_router
from .tasks_router import router as tasks_router
from .comments_router import router as comments_router
from src.routers.health_router import router as health_router

api_router = APIRouter(prefix="/api")

api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(tasks_router)
api_router.include_router(group_router)
api_router.include_router(comments_router)
api_router.include_router(health_router)
