"""Health and readiness probes."""

from fastapi import APIRouter
from sqlalchemy import text

from app.core.dependencies import DbSession

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Return ``ok`` if the process is up. Used by Docker/orchestrators."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe")
async def ready(session: DbSession) -> dict[str, str]:
    """Verify the database is reachable before declaring the app ready."""
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}
