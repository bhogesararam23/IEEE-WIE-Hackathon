"""Current-user business logic: profile upsert, consent, account erasure."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.soft_delete import soft_delete_user
from app.models.user import User, UserProfile
from app.schemas.user import UserProfilePayload

__all__ = [
    "get_user_with_profile",
    "record_consent",
    "soft_delete_account",
    "upsert_profile",
]


async def get_user_with_profile(session: AsyncSession, *, user_id: int) -> User | None:
    """Load a user together with their profile.

    ``selectinload`` rather than lazy access: touching ``user.profile`` later
    raises ``MissingGreenlet`` under async, and an explicit eager load turns that
    class of bug into a plain await here. The global soft-delete filter also
    applies to this load, so a deleted user is simply not found.
    """
    return await session.scalar(
        select(User).options(selectinload(User.profile)).where(User.id == user_id)
    )


async def upsert_profile(
    session: AsyncSession, *, user: User, payload: UserProfilePayload
) -> tuple[UserProfile, bool]:
    """Create or update the caller's profile. Returns ``(profile, created)``.

    Load and branch rather than relying on a bare ``ON CONFLICT DO UPDATE``: the
    audit trail has to distinguish "created" from "updated", and the caller needs
    to know which happened anyway to pick the right action name.
    """
    profile = await session.scalar(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )

    if profile is None:
        profile = UserProfile(user_id=user.id, **_profile_kwargs(payload))
        session.add(profile)
        created = True
    else:
        for field, value in _profile_kwargs(payload).items():
            setattr(profile, field, value)
        created = False

    await session.flush()
    return profile, created


def _profile_kwargs(payload: UserProfilePayload) -> dict:
    return {
        "context_type": payload.context_type,
        "trimester": payload.trimester,
        "infant_age_months": payload.infant_age_months,
        "is_premature_infant": payload.is_premature_infant,
    }


async def record_consent(session: AsyncSession, *, user: User) -> tuple[datetime, bool]:
    """Stamp ``consent_given_at``. Returns ``(timestamp, already_recorded)``.

    Idempotent, and idempotent *without moving the timestamp*. Re-posting consent
    must not overwrite the original date: the legally meaningful fact is when
    consent was first given, and a client that retries on a flaky connection
    would otherwise silently rewrite the audit-grade date.
    """
    if user.consent_given_at is not None:
        return user.consent_given_at, True

    now = datetime.now(UTC)
    user.consent_given_at = now
    await session.flush()
    return now, False


async def soft_delete_account(session: AsyncSession, *, user: User) -> datetime:
    """Tombstone the user and everything they own. Returns the deletion time.

    Idempotent: a second call keeps the original ``deleted_at`` and returns it,
    so "when did you delete my account" has a stable answer.
    """
    if user.deleted_at is not None:
        return user.deleted_at

    deleted_at = datetime.now(UTC)
    await soft_delete_user(session, user=user, deleted_at=deleted_at)
    return deleted_at
