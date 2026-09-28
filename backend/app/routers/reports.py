"""Reports endpoints: JSON medication summary and PDF download."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.core.deps import CurrentUser, DbSession, client_ip
from app.services import reports as reports_service
from app.services.audit import AuditAction, record

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/medication-summary",
    response_model=None,
    summary="JSON medication summary: medicines, alerts, duplicates, pending",
    responses={
        200: {"description": "Summary document.", "content": {"application/json": {}}},
        401: {"description": "Not authenticated."},
    },
)
async def medication_summary_json(
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> dict:
    """Return a full summary of the caller's medication state as JSON."""
    summary = await reports_service.build_medication_summary(session, user_id=user.id)
    await record(
        session,
        action=AuditAction.REPORT_GENERATED,
        resource_type="report",
        resource_id="medication_summary_json",
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return summary


@router.get(
    "/medication-summary/pdf",
    summary="Download medication summary as a PDF",
    responses={
        200: {
            "description": "PDF file.",
            "content": {"application/pdf": {}},
        },
        401: {"description": "Not authenticated."},
    },
)
async def medication_summary_pdf(
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> Response:
    """Render and stream a PDF medication report. Same data as the JSON endpoint."""
    summary = await reports_service.build_medication_summary(session, user_id=user.id)
    pdf_bytes = reports_service.render_pdf(summary)

    await record(
        session,
        action=AuditAction.REPORT_GENERATED,
        resource_type="report",
        resource_id="medication_summary_pdf",
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=medication_summary.pdf",
            "Content-Length": str(len(pdf_bytes)),
        },
    )
