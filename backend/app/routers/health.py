"""Liveness and readiness endpoints."""

from fastapi import APIRouter, Depends, Response
from fastapi import status as http_status

from app.schemas.health import HealthResponse
from app.services.health import STATUS_DEGRADED, collect_health_status

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description=(
        "Reports service metadata and live PostgreSQL connectivity. Returns 200 "
        "when every dependency is reachable and 503 when the database is down, "
        "so container orchestrators can gate traffic on it."
    ),
    responses={
        503: {"model": HealthResponse, "description": "A dependency is unreachable."}
    },
)
async def health_check(
    response: Response,
    report: HealthResponse = Depends(collect_health_status),
) -> HealthResponse:
    if report.status == STATUS_DEGRADED:
        response.status_code = http_status.HTTP_503_SERVICE_UNAVAILABLE
    return report
