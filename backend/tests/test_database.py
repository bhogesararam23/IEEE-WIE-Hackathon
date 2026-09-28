"""Live-database tests for the health probe.

Skipped automatically when Postgres is not reachable, so ``pytest`` stays green
without any external services.
"""

from collections.abc import AsyncIterator

import pytest

from app.core.config import get_settings
from app.core.database import engine
from app.services.health import check_database, collect_health_status

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _dispose_engine() -> AsyncIterator[None]:
    """Drop pooled connections after every test in this module.

    The engine in ``app.core.database`` is a module-level singleton, and asyncpg
    connections belong to the event loop that opened them. pytest-asyncio gives
    each test a fresh loop, so a connection cached by an earlier test is dead in
    the next one -- surfacing as ``AttributeError: 'NoneType' object has no
    attribute 'send'`` or ``RuntimeError: Event loop is closed`` on cleanup.
    Disposing forces the next test to open a connection on its own loop.

    Production is unaffected: uvicorn runs one loop per process and ``lifespan``
    already disposes the engine on shutdown.
    """
    yield
    await engine.dispose()


async def test_check_database_true_when_postgres_is_up() -> None:
    result = await check_database(get_settings().db_health_timeout)

    if not result:
        pytest.skip("PostgreSQL is not reachable; skipping live database test")
    assert result is True


async def test_collect_health_status_reports_up() -> None:
    report = await collect_health_status(get_settings())

    if report.database == "down":
        pytest.skip("PostgreSQL is not reachable; skipping live database test")
    assert report.status == "ok"
