"""Schemas for the current-user endpoints (``/users/me*``)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import UserContextType

__all__ = [
    "ConsentResponse",
    "CurrentUserResponse",
    "UserProfilePayload",
    "UserProfileResponse",
]


class UserProfilePayload(BaseModel):
    """Maternal context, used to create or update the current user's profile."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        # Partial updates are the point of an upsert, so omitting a field means
        # "leave it alone" rather than "clear it".
        extra="forbid",
    )

    context_type: UserContextType = Field(
        description="Which safety rules apply to this user."
    )
    trimester: int | None = Field(
        default=None, ge=1, le=3, description="1-3 when context_type is PREGNANT."
    )
    infant_age_months: int | None = Field(
        default=None, ge=0, le=240, description="Age in months when BREASTFEEDING."
    )
    is_premature_infant: bool | None = Field(
        default=None, description="Preterm infant flag; clinically significant."
    )

    @model_validator(mode="after")
    def _check_context_consistency(self) -> "UserProfilePayload":
        """Reject combinations that contradict the chosen context type.

        These would otherwise be storable nonsense: a "pregnant" user with a
        14-month-old infant, or a breastfeeding user with no infant age at all.
        The DB has CHECK constraints on the ranges but nothing can express the
        cross-field rule, so it lives here.
        """
        if self.context_type is UserContextType.PREGNANT:
            if self.trimester is None:
                raise ValueError(
                    "trimester is required when context_type is 'pregnant'"
                )
            if (
                self.infant_age_months is not None
                or self.is_premature_infant is not None
            ):
                raise ValueError(
                    "infant_age_months/is_premature_infant only apply when "
                    "context_type is 'breastfeeding'"
                )
        elif self.context_type is UserContextType.BREASTFEEDING:
            if self.infant_age_months is None:
                raise ValueError(
                    "infant_age_months is required when context_type is 'breastfeeding'"
                )
            if self.trimester is not None:
                raise ValueError(
                    "trimester only applies when context_type is 'pregnant'"
                )
        else:  # GENERAL -- neither field is meaningful
            if (
                self.trimester is not None
                or self.infant_age_months is not None
                or self.is_premature_infant is not None
            ):
                raise ValueError(
                    "trimester/infant fields must be null when "
                    "context_type is 'general'"
                )
        return self


class UserProfileResponse(BaseModel):
    """Stored profile, as returned by ``GET /users/me`` and the profile upsert."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    context_type: UserContextType
    trimester: int | None
    infant_age_months: int | None
    is_premature_infant: bool | None


class CurrentUserResponse(BaseModel):
    """``GET /users/me`` payload: the account plus its profile, if any."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    created_at: datetime
    consent_given_at: datetime | None = Field(
        description="When the user accepted the DPDP consent notice, if they have."
    )
    # A profile is optional: signup does not create one, and the client is
    # expected to prompt for it on first run.
    profile: UserProfileResponse | None = None


class ConsentResponse(BaseModel):
    """Confirmation that consent was recorded."""

    model_config = ConfigDict(from_attributes=True)

    consent_given_at: datetime
    already_recorded: bool = Field(
        description=(
            "True if consent was on file already. Re-posting is idempotent and "
            "never moves the original timestamp, so the earliest consent is what "
            "is provable."
        )
    )


class AccountDeletionResponse(BaseModel):
    """Confirmation of a soft-deleted account.

    ``hard_deleted`` is always False here. The field exists so the client does
    not have to infer retention from prose.
    """

    deleted_at: datetime
    hard_deleted: bool = False
    message: str = (
        "Account and all associated data have been soft-deleted. "
        "Your data is no longer returned by any endpoint."
    )
