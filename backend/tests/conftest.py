"""Shared pytest fixtures.

Tests never need a live database: the health service is injected through
``app.dependency_overrides`` so the endpoint contract can be verified in
isolation. The one test that does exercise real connectivity is marked
``integration`` and skips itself when Postgres is absent.
"""

from collections.abc import AsyncIterator, Callable, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.health import HealthResponse
from app.services.health import collect_health_status

HealthReportFactory = Callable[..., HealthResponse]


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
