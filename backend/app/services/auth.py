"""Signup and login business logic.

Routers stay thin; everything that touches a rule lives here so it can be
tested without a Request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User

logger = logging.getLogger(__name__)

__all__ = [
    "AuthResult",
    "DuplicateEmailError",
    "GoogleAuthError",
    "GoogleNotConfiguredError",
    "InvalidCredentialsError",
    "authenticate",
    "authenticate_google",
    "signup",
]


class DuplicateEmailError(Exception):
    """Raised when the email is already taken.

    Carries no detail beyond the fact of the conflict, and the router turns it
    into a 409 -- never a 500 from the unique-violation ``IntegrityError``.
    """


class InvalidCredentialsError(Exception):
    """Raised for an unknown email or a wrong password.

    The two cases are merged on purpose: telling a caller "no such user" leaks
    which addresses have accounts, which is a real enumeration vector.
    """


@dataclass(frozen=True, slots=True)
class AuthResult:
    user: User
    access_token: str
    expires_in: int


def _normalise(email: str) -> str:
    return email.strip().lower()


async def signup(
    session: AsyncSession, *, email: str, password: str, full_name: str
) -> User:
    """Create a user with a bcrypt-hashed password.

    The uniqueness check is a courtesy that produces a clean 409; the unique
    constraint is what actually guarantees it. Two concurrent signups for the
    same address can both pass the SELECT, so the ``IntegrityError`` path below
    is a real race, not dead code.
    """
    normalised = _normalise(email)

    existing = await session.scalar(
        select(User.id).where(func.lower(User.email) == normalised)
    )
    if existing is not None:
        raise DuplicateEmailError(normalised)

    user = User(
        email=normalised,
        # Hash before touching the session: bcrypt at cost 12 is deliberately
        # slow, and doing it inside a transaction holds a connection for ~250ms
        # for no reason.
        hashed_password=hash_password(password),
        full_name=full_name.strip(),
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Lost the race (or the pre-check was bypassed). uq_users_email.
        await session.rollback()
        raise DuplicateEmailError(normalised) from exc
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    """Return the user matching these credentials, or raise.

    Uses a dummy-hash comparison when the email is unknown so that the response
    time does not reveal whether an account exists. Without this, "no such user"
    returns in microseconds and "wrong password" takes ~250ms of bcrypt, and
    that gap is a reliable account-enumeration oracle.
    """
    normalised = _normalise(email)
    user = await session.scalar(
        # func.lower() rather than == : the stored value is already folded at
        # signup, but this keeps the comparison correct for rows written by an
        # import or a future admin tool.
        select(User).where(func.lower(User.email) == normalised)
    )

    if user is None:
        # Burn comparable CPU so the timing matches the "wrong password" path.
        verify_password(password, _DUMMY_HASH)
        raise InvalidCredentialsError

    if not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError

    return user


class GoogleNotConfiguredError(Exception):
    """``GOOGLE_CLIENT_ID`` is unset; the router turns this into a 503."""


class GoogleAuthError(Exception):
    """The ID token failed verification, or its email is unverified."""


async def authenticate_google(
    session: AsyncSession, *, credential: str
) -> tuple[User, bool]:
    """Verify a Google ID token and find-or-create the matching user.

    Returns ``(user, created)``. Trusts Google's signature over the claims --
    ``verify_oauth2_token`` checks signature, issuer, audience and expiry, and
    raises on any mismatch -- never anything the client asserts on its own.

    An email that already has a password-based account is treated as the same
    person: Google sign-in logs them into that existing row rather than
    creating a second account with the same address, which is the simpler
    behavior for someone who registered by hand and later clicks "Sign in
    with Google" on the same address.
    """
    settings = get_settings()
    if not settings.google_client_id:
        raise GoogleNotConfiguredError

    try:
        claims = google_id_token.verify_oauth2_token(
            credential, google_requests.Request(), settings.google_client_id
        )
    except ValueError as exc:
        raise GoogleAuthError(str(exc)) from exc

    email = claims.get("email")
    if not email or not claims.get("email_verified"):
        raise GoogleAuthError("Google account has no verified email")

    normalised = _normalise(email)
    user = await session.scalar(
        select(User).where(func.lower(User.email) == normalised)
    )
    if user is not None:
        return user, False

    full_name = (claims.get("name") or normalised.split("@")[0]).strip()[:200]
    user = User(
        email=normalised,
        hashed_password=None,
        full_name=full_name,
        # Matches the manual signup flow's immediate consent stamp (the
        # frontend calls giveConsent() right after signup, with no separate
        # confirmation step) -- a Google account gets the same net effect in
        # one round trip instead of two.
        consent_given_at=datetime.now(UTC),
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Lost a race against a concurrent signup/Google-login for the same
        # email -- same shape as signup()'s race handling.
        await session.rollback()
        user = await session.scalar(
            select(User).where(func.lower(User.email) == normalised)
        )
        if user is None:  # pragma: no cover - concurrent row would have to vanish too
            raise GoogleAuthError("could not create account") from exc
        return user, False
    return user, True


def issue_token(user: User) -> AuthResult:
    """Mint an access token for a user who has already been authenticated."""
    token, expires_in = create_access_token(user_id=user.id, email=user.email)
    return AuthResult(user=user, access_token=token, expires_in=expires_in)


# A valid cost-12 bcrypt digest of a throwaway string, used only to equalise
# timing on the unknown-email path. Precomputed and embedded rather than hashed
# at import: a live hash_password() here would add ~250ms of bcrypt to every
# process start. The plaintext is discarded; nobody can log in with it because
# no user row is ever compared against it.
_DUMMY_HASH = "$2b$12$xqLJD/A3rj6VYg32t0oTTu./sZMl6R1zo4Mrc3Zn6272g0TQq4YXW"
