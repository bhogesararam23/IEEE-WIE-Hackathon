"""Health-check logic backing ``GET /health``."""

import asyncio
import logging

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.core.database import engine
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
DATABASE_UP = "up"
DATABASE_DOWN = "down"


async def check_database(timeout_seconds: float) -> bool:
    """Return ``True`` when PostgreSQL answers a trivial query in time.

    Uses a throwaway connection rather than a request session so a failed probe
    cannot leave a poisoned session behind, and bounds the wait so ``/health``
    stays fast even while the database is down.
    """
    try:
        async with asyncio.timeout(timeout_seconds):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except (TimeoutError, SQLAlchemyError, OSError):
        logger.warning("Database health probe failed", exc_info=True)
        return False
    return True


async def collect_health_status(
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Assemble the health payload, probing the database once."""
    database_up = await check_database(settings.db_health_timeout)
    return HealthResponse(
        status=STATUS_OK if database_up else STATUS_DEGRADED,
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        database=DATABASE_UP if database_up else DATABASE_DOWN,
    )
