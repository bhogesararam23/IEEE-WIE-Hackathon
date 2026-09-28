"""Medicines on a user's medication list, and duplicate detection between them."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, utcnow
from app.models.enums import MedicineSourceType, MedicineStatus, enum_column

# The association table is imported as an object rather than referenced by the
# string "interaction_alert_medicines", so it is registered in Base.metadata
# even when only this module is imported.
from app.models.interaction import interaction_alert_medicines

if TYPE_CHECKING:
    from app.models.interaction import InteractionAlert
    from app.models.prescription import Prescription
    from app.models.reminder import ReminderSchedule
    from app.models.user import User


class Medicine(SoftDeleteMixin, TimestampMixin, Base):
    """A single medicine, from OCR extraction or typed in by the user.

    ``prescription_id`` is nullable so a user can add a medicine by hand;
    ``user_id`` is what actually scopes the row, since the same medicine can be
    reached through a prescription or on its own.
    """

    __tablename__ = "medicines"
    __table_args__ = (
        # The two signals used to spot the same drug entered twice.
        Index(
            "ix_medicines_user_normalized_ingredient",
            "user_id",
            "normalized_ingredient",
        ),
        CheckConstraint(
            "confidence_score IS NULL"
            " OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="ck_medicines_confidence_score",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int | None] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Exactly what was extracted from the image or typed by the user.
    raw_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_ingredient: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    brand_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Nullable: OCR output is frequently partial, and a missing dose must not
    # make the whole row unrepresentable.
    strength: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dose: Mapped[str | None] = mapped_column(String(100), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Confidence reported by the extraction model; NULL until reviewed.
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_confirmed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    status: Mapped[MedicineStatus] = mapped_column(
        enum_column(MedicineStatus, "medicine_status"),
        nullable=False,
        default=MedicineStatus.ACTIVE,
        server_default=MedicineStatus.ACTIVE.value,
    )

    @property
    def source(self) -> MedicineSourceType:
        """Where this row came from, derived from ``prescription_id``.

        Not a column: a row is either attached to an upload or it was typed in
        by hand, and a stored value could disagree with the FK the moment an
        upload was deleted. ``OTC`` is a judgement call the review UI can make
        later; the two cases we can actually prove are the ones returned here.
        """
        return (
            MedicineSourceType.PRESCRIPTION
            if self.prescription_id is not None
            else MedicineSourceType.SELF_REPORTED
        )

    prescription: Mapped["Prescription | None"] = relationship(
        back_populates="medicines"
    )
    user: Mapped["User"] = relationship(back_populates="medicines")
    # passive_deletes throughout: every foreign key pointing at this table is
    # ON DELETE CASCADE, so the database performs the cleanup.
    reminder_schedules: Mapped[list["ReminderSchedule"]] = relationship(
        back_populates="medicine",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    interaction_alerts: Mapped[list["InteractionAlert"]] = relationship(
        secondary=interaction_alert_medicines,
        back_populates="medicines",
        passive_deletes=True,
    )
    # DuplicateFlag points at this table twice, so each path needs its own name
    # and an explicit foreign_keys disambiguator. Without passive_deletes the
    # ORM would try to NULL medicine_id_a/medicine_id_b on delete.
    duplicate_flags_as_a: Mapped[list["DuplicateFlag"]] = relationship(
        back_populates="medicine_a",
        foreign_keys="DuplicateFlag.medicine_id_a",
        passive_deletes=True,
    )
    duplicate_flags_as_b: Mapped[list["DuplicateFlag"]] = relationship(
        back_populates="medicine_b",
        foreign_keys="DuplicateFlag.medicine_id_b",
        passive_deletes=True,
    )


class DuplicateFlag(SoftDeleteMixin, Base):
    """A suspected duplicate: the same drug listed twice under different names.

    Holds two FKs into ``medicines`` (a and b). A self-reference is prevented at
    the database level, and a given pair is only ever flagged once.
    """

    __tablename__ = "duplicate_flags"
    __table_args__ = (
        UniqueConstraint(
            "medicine_id_a", "medicine_id_b", name="uq_duplicate_flags_pair"
        ),
        CheckConstraint(
            "medicine_id_a <> medicine_id_b", name="ck_duplicate_flags_distinct"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_id_a: Mapped[int] = mapped_column(
        ForeignKey("medicines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    medicine_id_b: Mapped[int] = mapped_column(
        ForeignKey("medicines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    resolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    # Kept alongside the boolean so "when was this dismissed" does not require
    # grepping the audit log for a string match.
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    medicine_a: Mapped["Medicine"] = relationship(
        back_populates="duplicate_flags_as_a",
        foreign_keys=[medicine_id_a],
        passive_deletes=True,
    )
    medicine_b: Mapped["Medicine"] = relationship(
        back_populates="duplicate_flags_as_b",
        foreign_keys=[medicine_id_b],
        passive_deletes=True,
    )
