"""Declarative base plus the column mixins shared across models."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all HerMediSafe ORM models."""


def utcnow() -> datetime:
    """Timezone-aware current time, used as the Python-side column default.

    Paired with a ``server_default`` so rows still get a sensible timestamp when
    they are inserted by something other than the ORM.
    """
    return datetime.now(UTC)


class TimestampMixin:
    """Adds a ``created_at`` column to a model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds a ``deleted_at`` column for DPDP/GDPR-style right-to-erasure.

    Adding the column is only half the feature. The half that actually protects
    the user is the global ``deleted_at IS NULL`` filter installed in
    ``app.core.soft_delete``: it is applied by the ORM to *every* SELECT, so no
    future query can accidentally surface a deleted row. This mixin only
    supplies the storage.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        nullable=True,
        # Indexed because the global filter adds this predicate to every query.
        index=True,
    )

    @property
    def is_deleted(self) -> bool:
        """True once the row has been soft-deleted."""
        return self.deleted_at is not None
