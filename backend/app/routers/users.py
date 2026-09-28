"""Endpoints scoped to the authenticated caller. Every route needs a token."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.deps import CurrentUser, DbSession, client_ip
from app.schemas.user import (
    AccountDeletionResponse,
    ConsentResponse,
    CurrentUserResponse,
    UserProfilePayload,
    UserProfileResponse,
)
from app.services import users as users_service
from app.services.audit import AuditAction, record

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="Current user and their profile",
    responses={
        200: {"description": "The account; `profile` is null until one is set."},
        401: {"description": "Missing, malformed, expired, or revoked access token."},
    },
)
async def read_me(
    user: CurrentUser, request: Request, session: DbSession
) -> CurrentUserResponse:
    """Return the caller's account, including their profile if one exists.

    Reads through the global soft-delete filter, so a deleted account cannot
    reach this route at all -- ``get_current_user`` already 401d before we get
    here. The second load exists only to pull the profile in one round-trip
    instead of relying on a lazy load, which raises ``MissingGreenlet`` in async.
    """
    loaded = await users_service.get_user_with_profile(session, user_id=user.id)
    if loaded is None:  # pragma: no cover - the dependency already filtered it
        # Only reachable if the row is tombstoned between the dependency and
        # here, which needs a concurrent DELETE on the same account.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await record(
        session,
        action=AuditAction.PROFILE_READ,
        resource_type="user",
        resource_id=user.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return CurrentUserResponse.model_validate(loaded)


@router.post(
    "/me/profile",
    response_model=UserProfileResponse,
    summary="Create or update the current user's profile",
    responses={
        201: {"description": "Profile created."},
        200: {"description": "Existing profile updated."},
        401: {"description": "Not authenticated."},
        422: {
            "description": (
                "Validation failed, including context/demographic combinations "
                "that contradict each other, e.g. a pregnant user with no "
                "trimester."
            )
        },
    },
)
async def upsert_my_profile(
    payload: UserProfilePayload,
    user: CurrentUser,
    request: Request,
    response: Response,
    session: DbSession,
) -> UserProfileResponse:
    """Upsert the caller's maternal context.

    Returns 201 when a profile was created and 200 when one was updated, so a
    client can tell the two apart without diffing. The status has to be set on
    the ``Response`` rather than in the decorator because the route decorator
    takes a single fixed code.

    The audit action records which happened, because "when did this user's risk
    profile change" is the question an auditor actually asks.
    """
    profile, created = await users_service.upsert_profile(
        session, user=user, payload=payload
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    await record(
        session,
        action=AuditAction.PROFILE_CREATED if created else AuditAction.PROFILE_UPDATED,
        resource_type="user_profile",
        resource_id=profile.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return UserProfileResponse.model_validate(profile)


@router.post(
    "/me/consent",
    response_model=ConsentResponse,
    summary="Record that the user has given DPDP consent",
    responses={
        200: {"description": "Consent recorded. Idempotent; keeps the original time."},
        401: {"description": "Not authenticated."},
    },
)
async def give_consent(
    user: CurrentUser, request: Request, session: DbSession
) -> ConsentResponse:
    """Stamp ``users.consent_given_at``.

    Re-posting returns ``already_recorded=True`` and the *original* timestamp.
    Consent is never silently downgraded: this endpoint cannot revoke, and it
    cannot rewrite history to a later date.
    """
    consent_at, already = await users_service.record_consent(session, user=user)
    if not already:
        await record(
            session,
            action=AuditAction.CONSENT_RECORDED,
            resource_type="user",
            resource_id=user.id,
            user_id=user.id,
            ip_address=client_ip(request),
        )
        await session.commit()
    return ConsentResponse(consent_given_at=consent_at, already_recorded=already)


@router.delete(
    "/me",
    response_model=AccountDeletionResponse,
    summary="Soft-delete the caller's account and all associated data",
    responses={
        200: {"description": "Account and data tombstoned; returned by no endpoint."},
        401: {
            "description": (
                "Not authenticated, including a token for a deleted account."
            )
        },
    },
)
async def delete_my_account(
    user: CurrentUser, request: Request, session: DbSession
) -> AccountDeletionResponse:
    """Erase the caller's account DPDP-style: retain, tombstone, hide.

    Writes ``deleted_at`` across the user, profile, prescriptions, medicines,
    duplicate flags, interaction alerts, evidence references and reminder
    schedules. No row is removed, so the retention period can still be honoured
    or the account recovered -- but the global filter in
    ``app.core.soft_delete`` makes it invisible to the API from this moment on,
    and the caller's outstanding tokens stop working immediately.

    Audit logs are intentionally *not* tombstoned. Deleting the record of what
    happened to a user is the opposite of what an audit trail is for, and the
    row still points at a user record that exists but is hidden.
    """
    deleted_at = await users_service.soft_delete_account(session, user=user)
    await record(
        session,
        action=AuditAction.ACCOUNT_SOFT_DELETED,
        resource_type="user",
        resource_id=user.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return AccountDeletionResponse(deleted_at=deleted_at)
