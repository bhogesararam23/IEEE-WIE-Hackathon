"""User accounts and the maternal context that tailors safety checks."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.enums import UserContextType, enum_column

if TYPE_CHECKING:
    from app.models.audit import AuditLog
    from app.models.interaction import InteractionAlert
    from app.models.medicine import Medicine
    from app.models.prescription import Prescription
    from app.models.reminder import ReminderSchedule


class User(SoftDeleteMixin, TimestampMixin, Base):
    """A registered user.

    Every relationship below sets ``passive_deletes=True``. The child tables
    declare ``ON DELETE CASCADE``, so the database is the single owner of
    referential integrity; without this flag the ORM would *also* try to cascade
    in Python and would try to NULL out NOT NULL foreign keys, which raises
    ``NotNullViolationError`` the first time a user is deleted.

    That hard-delete path still exists and is still correct for a genuine
    erasure. ``DELETE /users/me`` deliberately does *not* use it: it stamps
    ``deleted_at`` across the whole graph via ``app.core.soft_delete`` so the
    data is retained-but-invisible, per the DPDP right-to-deletion brief.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 320 is the RFC 5321 maximum length of an address.
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # DPDP: explicit, timestamped opt-in. Set once by POST /users/me/consent;
    # never inferred from page visits.
    consent_given_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    profile: Mapped["UserProfile"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    prescriptions: Mapped[list["Prescription"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    medicines: Mapped[list["Medicine"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    interaction_alerts: Mapped[list["InteractionAlert"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reminder_schedules: Mapped[list["ReminderSchedule"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    # No passive_deletes here: audit_logs.user_id is ON DELETE SET NULL, so the
    # ORM clearing it produces exactly what the database would do anyway.
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")


class UserProfile(SoftDeleteMixin, Base):
    """The pregnancy/breastfeeding context used to grade medication safety."""

    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint(
            "trimester IS NULL OR trimester BETWEEN 1 AND 3",
            name="ck_user_profiles_trimester",
        ),
        CheckConstraint(
            "infant_age_months IS NULL OR infant_age_months >= 0",
            name="ck_user_profiles_infant_age",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    context_type: Mapped[UserContextType] = mapped_column(
        enum_column(UserContextType, "user_context_type"),
        nullable=False,
        default=UserContextType.GENERAL,
        server_default=UserContextType.GENERAL.value,
    )
    # Meaningful only when context_type is PREGNANT.
    trimester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Meaningful only when context_type is BREASTFEEDING.
    infant_age_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_premature_infant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    user: Mapped["User"] = relationship(back_populates="profile")
