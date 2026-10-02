import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.core.config import DATABASE_URL

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


_engine = None
_new_session = None
_tenant_autofill_installed = False


def _ensure_tenant_autofill() -> None:
    """Лениво регистрирует слушатель из src/db/tenant_scope.py при первом
    создании сессии — НЕ на верхнем уровне модуля: src.db.tenant_scope
    импортирует src.models.mixins, а импорт src.models (через __init__.py
    пакета) тянет модели, которые сами делают `from src.db import Base` —
    на верхнем уровне это даёт циклический импорт, потому что src.db ещё не
    успел доопределить Base на момент этого импорта. К моменту первого
    вызова get_session_maker()/get_engine() модуль src.db уже полностью
    загружен, поэтому здесь это безопасно."""
    global _tenant_autofill_installed
    if _tenant_autofill_installed:
        return
    from src.db.tenant_scope import install_tenant_autofill

    install_tenant_autofill()
    _tenant_autofill_installed = True


def get_engine():
    global _engine
    _ensure_tenant_autofill()
    if _engine is None:
        _engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
            connect_args={"server_settings": {"application_name": "mybot"}},
        )
    return _engine


def get_session_maker():
    global _new_session
    if _new_session is None:
        _new_session = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _new_session


async def get_session(retries: int = 5, delay: float = 2.0):
    session_maker = get_session_maker()
    try:
        async with session_maker() as session:
            yield session
    except Exception as e:
        # Здесь можно логировать, но не подавлять исключение
        logger.error(f"Database session error: {e}")
        raise  # важно: пробрасываем дальше


SessionDep = Annotated[AsyncSession, Depends(get_session)]


class Base(DeclarativeBase):
    pass
