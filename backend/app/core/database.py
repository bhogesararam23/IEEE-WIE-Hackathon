"""Async engine, session factory and the FastAPI session dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def _build_engine() -> AsyncEngine:
    """Create the process-wide async engine from configuration."""
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        # Silently replaces connections that the database dropped while idle.
        pool_pre_ping=True,
    )


engine: AsyncEngine = _build_engine()

# expire_on_commit=False keeps attributes readable after commit without an
# implicit refresh round-trip; autoflush=False defers flushes to explicit points.
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped session, rolling back if the handler raises.

    Register as a dependency wherever a route needs database access::

        @router.get("/things")
        async def list_things(db: AsyncSession = Depends(get_db)) -> ...: ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
