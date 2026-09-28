"""Schemas for interaction alerts and evidence references."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import InteractionSeverity

__all__ = [
    "EvidenceAddRequest",
    "EvidenceReferenceResponse",
    "InteractionAlertResponse",
    "InteractionCheckResponse",
]


class EvidenceReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_id: int
    title: str
    url: str
    retrieved_at: datetime


class InteractionAlertResponse(BaseModel):
    """A flagged DDI alert with its constituent medicine names and evidence."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    severity: InteractionSeverity
    rationale: str
    source_reference: str | None
    reviewed_by_professional: bool
    created_at: datetime
    medicine_names: list[str] = Field(
        default_factory=list,
        description="raw_name of the medicines involved in this interaction.",
    )
    evidence_references: list[EvidenceReferenceResponse] = Field(default_factory=list)


class InteractionCheckResponse(BaseModel):
    """Summary returned from POST /medicines/check-interactions."""

    new_alerts_created: int
    total_active_alerts: int


class EvidenceAddRequest(BaseModel):
    """Write source reference text and optional citation links to an alert."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    source_reference: str | None = Field(
        default=None,
        max_length=2048,
        description="Free-text source reference (e.g. PubMed link or AI summary).",
    )
    evidence_items: list[EvidenceItemIn] = Field(
        default_factory=list,
        description="Structured citation links to create as EvidenceReference rows.",
    )


class EvidenceItemIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    title: str = Field(max_length=512)
    url: str = Field(max_length=2048)


# Fix forward reference
EvidenceAddRequest.model_rebuild()
