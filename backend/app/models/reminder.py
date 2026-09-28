"""Reminder schedules for medicines the user is taking."""

from datetime import time
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.medicine import Medicine
    from app.models.user import User


class ReminderSchedule(SoftDeleteMixin, TimestampMixin, Base):
    """When to nudge the user about a medicine.

    ``frequency`` is free text ("daily", "twice_daily", "every_8_hours") rather
    than an enum, because the reminder engine is expected to grow new cadences
    and a native enum would need a migration for each one.
    """

    __tablename__ = "reminder_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    medicine_id: Mapped[int] = mapped_column(
        ForeignKey("medicines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    time_of_day: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    frequency: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    user: Mapped["User"] = relationship(back_populates="reminder_schedules")
    medicine: Mapped["Medicine"] = relationship(back_populates="reminder_schedules")
