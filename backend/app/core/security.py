"""Password hashing and JWT helpers.

Deliberately free of FastAPI imports so these stay cheap to unit test. Anything
that needs request context (``get_current_user``) lives in ``app/core/deps.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

__all__ = [
    "INVALID_TOKEN_REASON",
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "subject_to_user_id",
    "verify_password",
]

# Distinguishes access tokens from any future refresh token so a stolen refresh
# token cannot be replayed as a bearer token.
TOKEN_TYPE_ACCESS = "access"

# Machine-readable, never shown to the client directly; it becomes the
# WWW-Authenticate detail in the 401 body.
INVALID_TOKEN_REASON = "Could not validate credentials"


@lru_cache(maxsize=1)
def _pwd_context() -> CryptContext:
    """Build the bcrypt context once, with the cost factor from settings.

    The rounds must be configured on the context rather than passed to
    ``.hash()``: passlib 1.7 deprecates per-call settings and drops them in 2.0.
    Building it once also means the backend is constructed a single time.
    """
    return CryptContext(
        schemes=["bcrypt"],
        deprecated="auto",
        bcrypt__rounds=get_settings().bcrypt_rounds,
    )


def hash_password(plain_password: str) -> str:
    """Return a salted bcrypt digest of ``plain_password``.

    Bcrypt only considers the first 72 bytes, so callers must cap the input
    length (see ``Settings.max_password_length``). Raises ``ValueError`` if a
    longer password arrives rather than truncating it silently -- two different
    over-long passwords would otherwise produce the same digest.
    """
    if len(plain_password.encode("utf-8")) > 72:
        raise ValueError("password must not exceed 72 bytes")
    # Randsalt is on by default, so two identical passwords get different digests.
    return _pwd_context().hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a password against its stored digest.

    Returns ``False`` rather than raising on a malformed digest, so a corrupted
    row can never turn into a 500 on the login path.
    """
    try:
        return _pwd_context().verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        return False


def create_access_token(*, user_id: int, email: str) -> tuple[str, int]:
    """Mint a signed access token. Returns ``(token, expires_in_seconds)``."""
    settings = get_settings()
    now = datetime.now(UTC)
    expires_in = settings.access_token_expire_minutes * 60
    claims: dict[str, Any] = {
        # `sub` must be a string per RFC 7519 even though our PK is an int.
        "sub": str(user_id),
        "email": email,
        "type": TOKEN_TYPE_ACCESS,
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(claims, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature/expiry and return the claims.

    Raises:
        ValueError: on any validation failure, with ``INVALID_TOKEN_REASON`` as
            the message. Signature, expiry, issuer and token type are all
            checked, and every failure is collapsed into one error so a caller
            cannot probe which part of the token was wrong.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require_exp": True, "require_sub": True},
        )
    except JWTError as exc:
        raise ValueError(f"{INVALID_TOKEN_REASON}: {exc}") from exc

    if claims.get("type") != TOKEN_TYPE_ACCESS:
        raise ValueError(f"{INVALID_TOKEN_REASON}: wrong token type")
    return claims


def subject_to_user_id(claims: dict[str, Any]) -> int:
    """Pull ``user_id`` out of validated claims, rejecting non-numeric values."""
    raw = claims.get("sub")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{INVALID_TOKEN_REASON}: subject is not an integer") from exc
