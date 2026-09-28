"""Interaction check, alert listing, review, and evidence endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.core.deps import CurrentUser, DbSession, client_ip
from app.schemas.interaction import (
    EvidenceAddRequest,
    InteractionAlertResponse,
    InteractionCheckResponse,
)
from app.services import interactions as interactions_service
from app.services.audit import AuditAction, record

logger = logging.getLogger(__name__)

router = APIRouter(tags=["interactions"])

_ALERT_NOT_FOUND = "alert not found"


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _alert_to_response(alert) -> InteractionAlertResponse:  # noqa: ANN001
    return InteractionAlertResponse(
        id=alert.id,
        user_id=alert.user_id,
        severity=alert.severity,
        rationale=alert.rationale,
        source_reference=alert.source_reference,
        reviewed_by_professional=alert.reviewed_by_professional,
        created_at=alert.created_at,
        medicine_names=[m.raw_name for m in (alert.medicines or [])],
        evidence_references=list(alert.evidence_references or []),
    )


@router.post(
    "/medicines/check-interactions",
    response_model=InteractionCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Scan active medicines for drug–drug interactions",
    responses={
        200: {"description": "Check complete; new_alerts_created may be 0 if none found or all already flagged."},
        401: {"description": "Not authenticated."},
    },
)
async def check_interactions(
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> InteractionCheckResponse:
    """Run the mock DDI checker over the caller's confirmed active medicines.

    Idempotent: pairs that already have an open alert are not re-created.
    """
    new_alerts, total = await interactions_service.check_interactions(
        session, user_id=user.id
    )
    await record(
        session,
        action=AuditAction.INTERACTION_CHECK_RUN,
        resource_type="user",
        resource_id=user.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return InteractionCheckResponse(
        new_alerts_created=len(new_alerts),
        total_active_alerts=total,
    )


@router.get(
    "/alerts",
    response_model=list[InteractionAlertResponse],
    summary="List the caller's interaction alerts, severity-first",
    responses={401: {"description": "Not authenticated."}},
)
async def list_alerts(
    user: CurrentUser,
    session: DbSession,
) -> list[InteractionAlertResponse]:
    """Return all active DDI alerts for the caller, sorted high→moderate→low."""
    alerts = await interactions_service.list_alerts(session, user_id=user.id)
    return [_alert_to_response(a) for a in alerts]


@router.patch(
    "/alerts/{alert_id}/mark-reviewed",
    response_model=InteractionAlertResponse,
    summary="Mark an alert as reviewed by a clinician",
    responses={
        200: {"description": "Marked reviewed."},
        401: {"description": "Not authenticated."},
        404: {"description": "Alert not found or not the caller's."},
    },
)
async def mark_reviewed(
    alert_id: int,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> InteractionAlertResponse:
    try:
        alert = await interactions_service.mark_reviewed(
            session, user_id=user.id, alert_id=alert_id
        )
    except interactions_service.AlertAccessError as exc:
        raise _not_found(_ALERT_NOT_FOUND) from exc

    await record(
        session,
        action=AuditAction.INTERACTION_ALERT_REVIEWED,
        resource_type="interaction_alert",
        resource_id=alert.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return _alert_to_response(alert)


@router.patch(
    "/alerts/{alert_id}/evidence",
    response_model=InteractionAlertResponse,
    summary="Attach source reference / evidence citations to an alert",
    responses={
        200: {"description": "Evidence recorded."},
        401: {"description": "Not authenticated."},
        404: {"description": "Alert not found or not the caller's."},
    },
)
async def add_evidence(
    alert_id: int,
    payload: EvidenceAddRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> InteractionAlertResponse:
    """Write source_reference text and/or structured citations.

    This is the handoff endpoint for the RAG/AI service: it writes its
    retrieved evidence here so the review UI can surface it alongside the alert.
    """
    try:
        alert = await interactions_service.add_evidence(
            session,
            user_id=user.id,
            alert_id=alert_id,
            source_reference=payload.source_reference,
            evidence_items=[
                {"title": e.title, "url": e.url} for e in payload.evidence_items
            ],
        )
    except interactions_service.AlertAccessError as exc:
        raise _not_found(_ALERT_NOT_FOUND) from exc

    await record(
        session,
        action=AuditAction.INTERACTION_EVIDENCE_ADDED,
        resource_type="interaction_alert",
        resource_id=alert.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return _alert_to_response(alert)
