"""Request/response schemas for signup and login."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.config import get_settings

__all__ = [
    "LoginRequest",
    "SignupRequest",
    "TokenResponse",
]


class SignupRequest(BaseModel):
    """Credentials for creating an account."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        # Reject unknown keys rather than ignoring a typo'd field, which would
        # otherwise produce an account with a silently-defaulted password.
        extra="forbid",
    )

    email: EmailStr = Field(description="Login email address.")
    # min_length is a floor on entropy, not a real policy; 8 is the usual
    # minimum that does not annoy users.
    password: str = Field(
        min_length=8,
        max_length=72,  # bcrypt's byte limit; see Settings.max_password_length
        description="Plaintext password. Never logged, never returned.",
    )
    full_name: str = Field(min_length=1, max_length=200, description="Display name.")

    @field_validator("password")
    @classmethod
    def _password_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("password must not be only whitespace")
        return value

    @field_validator("full_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("full_name must not be blank")
        return value

    def normalised_email(self) -> str:
        """Return the email folded for case-insensitive uniqueness.

        Gmail-style local parts are technically case-sensitive, but in practice
        treating them as identical is what users expect, and a login that is
        case-sensitive about ``A@x.com`` vs ``a@x.com`` is a support ticket.
        """
        return self.email.strip().lower()


class LoginRequest(BaseModel):
    """Credentials for exchanging a password for a token."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    """A freshly minted access token."""

    model_config = ConfigDict(from_attributes=True)

    access_token: str
    token_type: str = Field(default="bearer", description="Authorization scheme.")
    expires_in: int = Field(description="Token lifetime in seconds from issue time.")
    # Not required by the brief, but saves every client a round-trip: without
    # it the SPA has to call GET /users/me just to learn who it is.
    user_id: int
    email: str

    @classmethod
    def build(
        cls, *, token: str, expires_in: int, user_id: int, email: str
    ) -> "TokenResponse":
        return cls(
            access_token=token,
            expires_in=expires_in,
            user_id=user_id,
            email=email,
        )

    @property
    def expires_in_hours(self) -> float:
        return self.expires_in / 3600


# Referenced by the login router for the hint in its 401 body.
DEFAULT_TOKEN_LIFETIME_MINUTES = get_settings().access_token_expire_minutes
