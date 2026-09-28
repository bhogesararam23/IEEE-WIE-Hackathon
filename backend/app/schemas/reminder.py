"""Schemas for reminder schedules."""

from __future__ import annotations

from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ReminderCreateRequest",
    "ReminderResponse",
    "ReminderUpdateRequest",
]


class ReminderCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    medicine_id: int = Field(description="The confirmed medicine to set a reminder for.")
    time_of_day: time = Field(
        description="Time to send the reminder, e.g. '08:00:00'."
    )
    frequency: str = Field(
        max_length=50,
        description=(
            "Cadence string: 'daily', 'twice_daily', 'three_times_daily', "
            "'every_8_hours', 'weekly', etc."
        ),
    )


class ReminderUpdateRequest(BaseModel):
    """Partial update — only supplied fields are changed."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    time_of_day: time | None = None
    frequency: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    medicine_id: int
    medicine_name: str = Field(
        description="raw_name of the associated medicine for display convenience."
    )
    time_of_day: time
    frequency: str
    is_active: bool
    created_at: datetime
