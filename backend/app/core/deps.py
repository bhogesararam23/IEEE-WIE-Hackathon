"""Request-scoped dependencies: the authenticated current user."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token, subject_to_user_id
from app.models.user import User

__all__ = [
    "CurrentUser",
    "DbSession",
    "client_ip",
    "get_current_user",
    "get_optional_user",
]


# The injected session, aliased so every signature below reads the same way.
DbSession = Annotated[AsyncSession, Depends(get_db)]


def client_ip(request: Request) -> str | None:
    """Best-effort client IP for the audit trail, truncated to fit ``String(45)``.

    Takes the left-most ``X-Forwarded-For`` entry, which is the original client
    when a proxy appended to the chain. With no proxy the header is absent and
    this falls back to the socket peer. 45 chars is the longest possible IPv6
    textual form.

    Lives here rather than in a router because both routers need it and it is
    request context, not routing.
    """
    forwarded = request.headers.get("x-forwarded-for")
    candidate = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else None)
    )
    return candidate[:45] if candidate else None


# auto_error=False so a missing header produces our own 401 body instead of
# FastAPI's bare {"detail":"Not authenticated"} -- and so the scheme check below
# is actually reachable.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


def _unauthorised(detail: str) -> HTTPException:
    """401 with the RFC 6750 challenge header, as the spec requires."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DbSession,
) -> User:
    """Resolve the ``Authorization: Bearer <jwt>`` header to a live ``User``.

    A token is only ever half the answer. After verifying the signature we still
    load the user from the database, because a valid signature says the token is
    authentic, not that the account is still active. This is what makes
    ``DELETE /users/me`` actually revoke access: the global soft-delete filter in
    ``app.core.soft_delete`` hides the tombstoned row, this lookup returns
    ``None``, and every existing token for that user starts returning 401 with no
    token blacklist needed.

    Fails closed with 401 for: no header, wrong scheme, bad signature, expired
    token, wrong token type, unknown subject, or a soft-deleted account.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorised("Not authenticated")

    try:
        claims = decode_access_token(credentials.credentials)
        user_id = subject_to_user_id(claims)
    except ValueError:
        # Deliberately does not echo the underlying reason (expired vs bad
        # signature) to the client.
        raise _unauthorised("Could not validate credentials") from None

    # A select(), not session.get(): loader criteria -- i.e. the soft-delete
    # filter -- are applied to selects, but not to the identity-map fast path.
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise _unauthorised("Could not validate credentials")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_optional_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DbSession,
) -> User | None:
    """Same as :func:`get_current_user` but returns ``None`` instead of raising.

    For endpoints that behave differently for signed-in users but must stay
    publicly reachable. Note the asymmetry, which is intentional: a *present but
    invalid* token still 401s, because silently treating garbage credentials as
    anonymous is how a broken client goes unnoticed.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    try:
        user_id = subject_to_user_id(decode_access_token(credentials.credentials))
    except ValueError:
        raise _unauthorised("Could not validate credentials") from None
    return await session.scalar(select(User).where(User.id == user_id))
