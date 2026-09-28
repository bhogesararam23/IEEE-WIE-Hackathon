"""Shared pytest fixtures.

The suite runs against a throwaway ``<dev database>_test`` database, created and
migrated on first use. The DB-backed tests truncate every table between cases, so
running them against the development database would destroy the seeded demo
accounts minutes before a presentation.

Tests never need a live database for the endpoint contracts: the health service
is injected through ``app.dependency_overrides``. The ones that do open real
connections fail loudly when Postgres is absent.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _test_database_url() -> str:
    """Re-point ``DATABASE_URL`` at a sibling database for the test run.

    Read from ``.env`` through the same settings object the app uses, then have
    the environment win over it. This must happen before ``app.core.database`` is
    imported, because that module builds its engine at import time.
    """
    from app.core.config import Settings  # no engine, so no connection side effects

    url = os.environ.get("DATABASE_URL") or Settings().database_url
    parts = urlsplit(url)
    name = os.environ.get("TEST_DATABASE_NAME", f"{parts.path.lstrip('/')}_test")
    return urlunsplit(parts._replace(path=f"/{name}"))


TEST_DATABASE_URL = _test_database_url()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas.health import HealthResponse  # noqa: E402
from app.services.health import collect_health_status  # noqa: E402

HealthReportFactory = Callable[..., HealthResponse]


def _migrate_to_head() -> None:
    """Bring the test schema to head. Runs in a worker thread, see below."""
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    # Absolute path so the migration works no matter which directory pytest started in.
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(config, "head")


async def _provision() -> None:
    """Create the test database if it does not exist, then migrate it."""
    parts = urlsplit(TEST_DATABASE_URL)
    database = parts.path.lstrip("/")
    maintenance = urlunsplit(
        (parts.scheme.replace("+asyncpg", ""), parts.netloc, "/postgres", "", "")
    )

    conn = await asyncpg.connect(maintenance)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", database
        )
        if not exists:
            # IF NOT EXISTS rather than a quoted identifier: the name is derived
            # from a developer-controlled URL, and Postgres cannot bind it.
            await conn.execute(f'CREATE DATABASE "{database}"')
    finally:
        await conn.close()

    # env.py calls asyncio.run(), which refuses to nest inside this loop, so the
    # migration gets a thread with no running loop of its own.
    with ThreadPoolExecutor(max_workers=1) as pool:
        await asyncio.get_running_loop().run_in_executor(pool, _migrate_to_head)


@pytest.fixture(scope="session", autouse=True)
def provision_test_database() -> None:
    """Provision the test database once per run, and tolerate Postgres being down.

    An unreachable server is reported rather than raised: the contract tests need
    no database at all, and they should stay runnable for someone who has only
    cloned the repo.
    """
    try:
        asyncio.run(_provision())
    except (OSError, asyncpg.PostgresError) as exc:
        print(
            f"\n[conftest] Could not provision {TEST_DATABASE_URL}: {exc}. "
            "Database-backed tests will fail."
        )


@pytest.fixture
def application() -> Iterator[FastAPI]:
    """The application under test, with dependency overrides cleaned up."""
    app.dependency_overrides.clear()
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def health_report() -> HealthReportFactory:
    """Build a health payload for stubbing."""

    def _make(status: str = "ok", database: str = "up") -> HealthResponse:
        return HealthResponse(
            status=status,  # type: ignore[arg-type]
            service="HerMediSafe API",
            version="0.1.0",
            environment="test",
            database=database,  # type: ignore[arg-type]
        )

    return _make


@pytest.fixture
def override_health(application: FastAPI) -> Callable[[HealthResponse], None]:
    """Stub the health service. The yielded callable replaces the report."""

    def _set(report: HealthResponse) -> None:
        application.dependency_overrides[collect_health_status] = lambda: report

    _set(
        HealthResponse(
            status="ok",
            service="HerMediSafe API",
            version="0.1.0",
            environment="test",
            database="up",
        )
    )
    return _set


@pytest.fixture
async def client(
    application: FastAPI, override_health: Callable
) -> AsyncIterator[AsyncClient]:
    """In-process HTTP client wired to the app over ASGI (no socket, no server)."""
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as http_client:
        yield http_client
