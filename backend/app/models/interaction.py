"""Interaction alerts between medicines, plus their evidence citations.

``medicine_ids`` is modelled as a proper join table rather than a PostgreSQL
array: the rows then have real foreign keys, so deleting a medicine cannot leave
a dangling id behind, and "which medicines are in this alert" stays indexable
for the query the safety screen will actually run.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, utcnow
from app.models.enums import InteractionSeverity, enum_column

if TYPE_CHECKING:
    from app.models.medicine import Medicine
    from app.models.user import User

interaction_alert_medicines = Table(
    "interaction_alert_medicines",
    Base.metadata,
    Column(
        "alert_id",
        ForeignKey("interaction_alerts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "medicine_id",
        ForeignKey("medicines.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # Serves "find the alerts for this medicine".
    Index("ix_interaction_alert_medicines_medicine_id", "medicine_id"),
)


class InteractionAlert(SoftDeleteMixin, TimestampMixin, Base):
    """A flagged interaction between two or more of a user's medicines."""

    __tablename__ = "interaction_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    severity: Mapped[InteractionSeverity] = mapped_column(
        enum_column(InteractionSeverity, "interaction_severity"),
        nullable=False,
        index=True,
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    # Populated later by the AI service; NULL until then.
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_professional: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    user: Mapped["User"] = relationship(back_populates="interaction_alerts")
    medicines: Mapped[list["Medicine"]] = relationship(
        secondary=interaction_alert_medicines,
        back_populates="interaction_alerts",
        passive_deletes=True,
    )
    evidence_references: Mapped[list["EvidenceReference"]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class EvidenceReference(SoftDeleteMixin, Base):
    """A citation backing an alert. Mostly written by the AI service."""

    __tablename__ = "evidence_references"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("interaction_alerts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )

    alert: Mapped["InteractionAlert"] = relationship(
        back_populates="evidence_references"
    )
