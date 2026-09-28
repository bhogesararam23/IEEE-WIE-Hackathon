"""Schemas backing the health endpoint."""

from typing import Literal

from pydantic import BaseModel, Field

ServiceStatus = Literal["ok", "degraded"]
ComponentStatus = Literal["up", "down"]


class HealthResponse(BaseModel):
    """Payload returned by ``GET /health``."""

    status: ServiceStatus = Field(
        description="Overall status; 'degraded' when a dependency is unreachable."
    )
    service: str = Field(description="Configured service name.")
    version: str = Field(description="Application version.")
    environment: str = Field(description="Deployment environment name.")
    database: ComponentStatus = Field(description="PostgreSQL connectivity status.")
