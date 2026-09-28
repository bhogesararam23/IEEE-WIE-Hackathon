"""Signup and login. Public routes -- no authentication required."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import client_ip
from app.schemas.auth import (
    GoogleAuthRequest,
    LoginRequest,
    SignupRequest,
    TokenResponse,
)
from app.services import auth as auth_service
from app.services.audit import AuditAction, record

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and return an access token",
    responses={
        201: {
            "description": (
                "Account created. A token is returned so the client does not have "
                "to log in as a second step."
            )
        },
        409: {"description": "That email is already registered."},
        422: {
            "description": (
                "Validation failed, e.g. password too short or malformed email."
            )
        },
    },
)
async def signup(
    payload: SignupRequest, request: Request, session: SessionDep
) -> TokenResponse:
    """Register a user, hash the password with bcrypt, and sign them straight in.

    Returns 201 with a token rather than a bare confirmation: forcing an
    immediate second round-trip to /auth/login after signup is a pointless
    failure mode, and a client that mishandles it usually just leaves the user
    staring at a "account created, now log in" screen.
    """
    ip = client_ip(request)
    try:
        user = await auth_service.signup(
            session,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
        )
    except auth_service.DuplicateEmailError:
        # Commit the failure audit in its own transaction: the user insert was
        # rolled back, and a conflict attempt is still worth recording.
        await record(
            session,
            action=AuditAction.SIGNUP_FAILED,
            resource_type="user",
            resource_id=payload.email,
            user_id=None,
            ip_address=ip,
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        ) from None

    result = auth_service.issue_token(user)
    await record(
        session,
        action=AuditAction.SIGNUP,
        resource_type="user",
        resource_id=user.id,
        user_id=user.id,
        ip_address=ip,
    )
    await session.commit()
    return TokenResponse.build(
        token=result.access_token,
        expires_in=result.expires_in,
        user_id=user.id,
        email=user.email,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange email + password for a 24h access token",
    responses={
        200: {"description": "Authenticated; returns a bearer token."},
        401: {
            "description": (
                "Unknown email or wrong password -- deliberately indistinguishable."
            )
        },
        422: {"description": "Validation failed."},
    },
)
async def login(
    payload: LoginRequest, request: Request, session: SessionDep
) -> TokenResponse:
    """Verify credentials and mint a JWT.

    The 401 body is identical for "no such user" and "wrong password" so the
    endpoint cannot be used to enumerate which addresses have accounts. A
    soft-deleted account fails here too: the global filter hides the row, so it
    is indistinguishable from never having existed.
    """
    ip = client_ip(request)
    try:
        user = await auth_service.authenticate(
            session, email=payload.email, password=payload.password
        )
    except auth_service.InvalidCredentialsError:
        await record(
            session,
            action=AuditAction.LOGIN_FAILED,
            resource_type="user",
            resource_id=payload.email,
            user_id=None,
            ip_address=ip,
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    result = auth_service.issue_token(user)
    await record(
        session,
        action=AuditAction.LOGIN,
        resource_type="user",
        resource_id=user.id,
        user_id=user.id,
        ip_address=ip,
    )
    await session.commit()
    return TokenResponse.build(
        token=result.access_token,
        expires_in=result.expires_in,
        user_id=user.id,
        email=user.email,
    )


@router.post(
    "/google",
    response_model=TokenResponse,
    summary="Exchange a verified Google ID token for an access token",
    responses={
        200: {
            "description": "Authenticated (or a new account was created); "
            "returns a bearer token."
        },
        401: {
            "description": "The ID token failed verification, or its email "
            "is unverified."
        },
        422: {"description": "Validation failed."},
        503: {"description": "GOOGLE_CLIENT_ID is not configured on this server."},
    },
)
async def google_auth(
    payload: GoogleAuthRequest, request: Request, session: SessionDep
) -> TokenResponse:
    """Verify a Google Identity Services credential and sign the user in.

    Finds an existing account by the token's (Google-verified) email, or
    creates one -- see ``auth_service.authenticate_google`` for exactly how
    that decision is made and why. Issues the same kind of app JWT as
    ``/auth/login``, so nothing downstream needs to know how the session
    started.
    """
    ip = client_ip(request)
    try:
        user, created = await auth_service.authenticate_google(
            session, credential=payload.credential
        )
    except auth_service.GoogleNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured on this server",
        ) from None
    except auth_service.GoogleAuthError as exc:
        await record(
            session,
            action=AuditAction.GOOGLE_LOGIN_FAILED,
            resource_type="user",
            resource_id="unknown",
            user_id=None,
            ip_address=ip,
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not verify Google credential: {exc}",
        ) from None

    result = auth_service.issue_token(user)
    await record(
        session,
        action=AuditAction.GOOGLE_SIGNUP if created else AuditAction.GOOGLE_LOGIN,
        resource_type="user",
        resource_id=user.id,
        user_id=user.id,
        ip_address=ip,
    )
    await session.commit()
    return TokenResponse.build(
        token=result.access_token,
        expires_in=result.expires_in,
        user_id=user.id,
        email=user.email,
    )
