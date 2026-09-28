"""Audit log read-access endpoint — users can see their own trail."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.core.deps import CurrentUser, DbSession, client_ip
from app.models.audit import AuditLog
from app.schemas.audit import AuditLogListResponse, AuditLogResponse
from app.services.audit import AuditAction, record
from sqlalchemy import func, select

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get(
    "",
    response_model=AuditLogListResponse,
    summary="View your own audit trail (paginated, newest first)",
    responses={401: {"description": "Not authenticated."}},
)
async def list_audit_logs(
    request: Request,
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AuditLogListResponse:
    """Return the caller's audit log entries, most recent first.

    This record itself is audited: reading the trail leaves a trace so an
    administrator can see when a user accessed their own history.
    """
    # Use the include_deleted context manager: audit logs are excluded from the
    # soft-delete filter (they have no deleted_at), but we use a direct select.
    total = int(
        await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.user_id == user.id)
        )
        or 0
    )
    rows = list(
        (
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.user_id == user.id)
                .order_by(AuditLog.timestamp.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )

    # Record the read action (flush before commit so it lands in the same txn)
    await record(
        session,
        action=AuditAction.AUDIT_LOG_READ,
        resource_type="audit_logs",
        resource_id=str(user.id),
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()

    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )
