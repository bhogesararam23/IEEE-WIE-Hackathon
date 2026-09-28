"""Contract tests for ``GET /health``."""

from collections.abc import Callable

from httpx import AsyncClient

from app.schemas.health import HealthResponse


async def test_health_returns_ok_when_database_is_up(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"
    assert body["service"] == "HerMediSafe API"


async def test_health_returns_503_when_database_is_down(
    client: AsyncClient,
    override_health: Callable[[HealthResponse], None],
    health_report: Callable[..., HealthResponse],
) -> None:
    override_health(health_report(status="degraded", database="down"))

    response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "down"


async def test_health_response_matches_schema(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.headers["content-type"].startswith("application/json")
    assert set(response.json()) == {
        "status",
        "service",
        "version",
        "environment",
        "database",
    }


async def test_health_is_listed_in_openapi(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]


async def test_root_points_at_docs_and_health(client: AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "HerMediSafe API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
