from fastapi import APIRouter
from sqlalchemy import text
from src.db import SessionDep

router = APIRouter(tags=["System"])


@router.get("/health", include_in_schema=False)
async def health(session: SessionDep):
    try:
        await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "db": db_status,
    }
