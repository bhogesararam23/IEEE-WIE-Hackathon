"""Reminder schedule CRUD service."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import MedicineStatus
from app.models.medicine import Medicine
from app.models.reminder import ReminderSchedule
from app.schemas.reminder import ReminderCreateRequest, ReminderUpdateRequest

logger = logging.getLogger(__name__)

__all__ = [
    "ReminderAccessError",
    "ReminderValidationError",
    "create_reminder",
    "delete_reminder",
    "list_reminders",
    "update_reminder",
]


class ReminderAccessError(LookupError):
    """The reminder does not exist, or is not the caller's."""


class ReminderValidationError(ValueError):
    """The requested operation is invalid (e.g. medicine not confirmed)."""


async def create_reminder(
    session: AsyncSession, *, user_id: int, payload: ReminderCreateRequest
) -> ReminderSchedule:
    """Create a reminder for a confirmed medicine the user owns."""
    medicine = await session.scalar(
        select(Medicine).where(
            Medicine.id == payload.medicine_id,
            Medicine.user_id == user_id,
        )
    )
    if medicine is None:
        raise ReminderAccessError(f"medicine {payload.medicine_id} not found")
    if not medicine.is_confirmed:
        raise ReminderValidationError("only confirmed medicines can have reminders")

    reminder = ReminderSchedule(
        user_id=user_id,
        medicine_id=payload.medicine_id,
        time_of_day=payload.time_of_day,
        frequency=payload.frequency,
        is_active=True,
    )
    session.add(reminder)
    await session.flush()
    logger.info("Created reminder %s for user %s medicine %s", reminder.id, user_id, payload.medicine_id)
    return reminder


async def list_reminders(
    session: AsyncSession, *, user_id: int, is_active: bool | None = None
) -> list[ReminderSchedule]:
    """Return the user's reminders, optionally filtered by active status."""
    conditions = [ReminderSchedule.user_id == user_id]
    if is_active is not None:
        conditions.append(ReminderSchedule.is_active.is_(is_active))
    return list(
        (
            await session.scalars(
                select(ReminderSchedule)
                .where(*conditions)
                .options(selectinload(ReminderSchedule.medicine))
                .order_by(ReminderSchedule.created_at.desc())
            )
        ).all()
    )


async def update_reminder(
    session: AsyncSession,
    *,
    user_id: int,
    reminder_id: int,
    payload: ReminderUpdateRequest,
) -> ReminderSchedule:
    reminder = await _get_reminder(session, user_id=user_id, reminder_id=reminder_id)
    if payload.time_of_day is not None:
        reminder.time_of_day = payload.time_of_day
    if payload.frequency is not None:
        reminder.frequency = payload.frequency
    if payload.is_active is not None:
        reminder.is_active = payload.is_active
    await session.flush()
    return reminder


async def delete_reminder(
    session: AsyncSession, *, user_id: int, reminder_id: int
) -> ReminderSchedule:
    """Soft-delete a reminder."""
    reminder = await _get_reminder(session, user_id=user_id, reminder_id=reminder_id)
    reminder.deleted_at = datetime.now(UTC)
    await session.flush()
    return reminder


async def _get_reminder(
    session: AsyncSession, *, user_id: int, reminder_id: int
) -> ReminderSchedule:
    reminder = await session.scalar(
        select(ReminderSchedule)
        .where(ReminderSchedule.id == reminder_id, ReminderSchedule.user_id == user_id)
        .options(selectinload(ReminderSchedule.medicine))
    )
    if reminder is None:
        raise ReminderAccessError(f"reminder {reminder_id} not found")
    return reminder
