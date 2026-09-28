"""Reminder schedule CRUD endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.deps import CurrentUser, DbSession, client_ip
from app.schemas.reminder import ReminderCreateRequest, ReminderResponse, ReminderUpdateRequest
from app.services import reminders as reminders_service
from app.services.audit import AuditAction, record

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reminders", tags=["reminders"])

_REMINDER_NOT_FOUND = "reminder not found"


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _reminder_response(reminder) -> ReminderResponse:  # noqa: ANN001
    return ReminderResponse(
        id=reminder.id,
        user_id=reminder.user_id,
        medicine_id=reminder.medicine_id,
        medicine_name=reminder.medicine.raw_name if reminder.medicine else "",
        time_of_day=reminder.time_of_day,
        frequency=reminder.frequency,
        is_active=reminder.is_active,
        created_at=reminder.created_at,
    )


@router.post(
    "",
    response_model=ReminderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reminder for a confirmed medicine",
    responses={
        201: {"description": "Reminder created."},
        401: {"description": "Not authenticated."},
        404: {"description": "Medicine not found or not the caller's."},
        422: {"description": "Medicine is not yet confirmed."},
    },
)
async def create_reminder(
    payload: ReminderCreateRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> ReminderResponse:
    try:
        reminder = await reminders_service.create_reminder(
            session, user_id=user.id, payload=payload
        )
    except reminders_service.ReminderAccessError as exc:
        raise _not_found(str(exc)) from exc
    except reminders_service.ReminderValidationError as exc:
        raise _unprocessable(str(exc)) from exc

    await record(
        session,
        action=AuditAction.REMINDER_CREATED,
        resource_type="reminder",
        resource_id=reminder.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    # Reload with medicine relationship populated for the response
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.reminder import ReminderSchedule
    reminder = await session.scalar(
        select(ReminderSchedule)
        .where(ReminderSchedule.id == reminder.id)
        .options(selectinload(ReminderSchedule.medicine))
    )
    return _reminder_response(reminder)


@router.get(
    "",
    response_model=list[ReminderResponse],
    summary="List the caller's reminders",
    responses={401: {"description": "Not authenticated."}},
)
async def list_reminders(
    user: CurrentUser,
    session: DbSession,
    is_active: bool | None = Query(default=None, description="Filter by active status."),
) -> list[ReminderResponse]:
    reminders = await reminders_service.list_reminders(
        session, user_id=user.id, is_active=is_active
    )
    return [_reminder_response(r) for r in reminders]


@router.patch(
    "/{reminder_id}",
    response_model=ReminderResponse,
    summary="Update a reminder's schedule or active status",
    responses={
        200: {"description": "Updated."},
        401: {"description": "Not authenticated."},
        404: {"description": "Reminder not found or not the caller's."},
    },
)
async def update_reminder(
    reminder_id: int,
    payload: ReminderUpdateRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> ReminderResponse:
    try:
        reminder = await reminders_service.update_reminder(
            session, user_id=user.id, reminder_id=reminder_id, payload=payload
        )
    except reminders_service.ReminderAccessError as exc:
        raise _not_found(_REMINDER_NOT_FOUND) from exc

    await record(
        session,
        action=AuditAction.REMINDER_UPDATED,
        resource_type="reminder",
        resource_id=reminder.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return _reminder_response(reminder)


@router.delete(
    "/{reminder_id}",
    response_model=ReminderResponse,
    summary="Remove a reminder (soft delete)",
    responses={
        200: {"description": "Soft-deleted; response describes the tombstoned row."},
        401: {"description": "Not authenticated."},
        404: {"description": "Reminder not found or not the caller's."},
    },
)
async def delete_reminder(
    reminder_id: int,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> ReminderResponse:
    try:
        reminder = await reminders_service.delete_reminder(
            session, user_id=user.id, reminder_id=reminder_id
        )
    except reminders_service.ReminderAccessError as exc:
        raise _not_found(_REMINDER_NOT_FOUND) from exc

    await record(
        session,
        action=AuditAction.REMINDER_DELETED,
        resource_type="reminder",
        resource_id=reminder_id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return _reminder_response(reminder)
