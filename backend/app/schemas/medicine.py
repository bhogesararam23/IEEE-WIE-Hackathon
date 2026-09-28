"""Schemas for the medicine list, review actions, and duplicate flags."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import MedicineSourceType, MedicineStatus

__all__ = [
    "DuplicateFlagResponse",
    "DuplicateResolveRequest",
    "DuplicateResolveResponse",
    "JanAushadhiOption",
    "ManualMedicineRequest",
    "MedicineConfirmRequest",
    "MedicineRejectRequest",
    "MedicineResponse",
    "PrescriptionMedicine",
]


class JanAushadhiOption(BaseModel):
    """A cheaper PMBJP generic-equivalent product for a medicine's ingredient."""

    model_config = ConfigDict(from_attributes=True)

    product_name: str
    unit: str
    mrp_inr: float


class MedicineResponse(BaseModel):
    """A medicine as the user's list sees it.

    ``source`` is derived from ``prescription_id`` rather than stored: a row is
    either attached to an upload or it was typed in by hand, and there is no
    third case worth a column.

    No ``updated_at``: the models carry ``created_at`` only, and inventing an
    ``updated_at`` in the response shape would promise a value the API cannot
    actually supply.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    prescription_id: int | None
    source: MedicineSourceType
    raw_name: str
    normalized_ingredient: str | None = Field(
        description=(
            "Canonical generic ingredient, set on confirmation. Null while the "
            "row is unconfirmed or if no mapping matched."
        )
    )
    brand_name: str | None
    strength: str | None
    dose: str | None
    frequency: str | None
    duration: str | None
    confidence_score: float | None = Field(
        description="Extractor's confidence (0-1); null once the user has confirmed."
    )
    is_confirmed: bool
    status: MedicineStatus
    created_at: datetime
    jan_aushadhi: JanAushadhiOption | None = Field(
        default=None,
        description="Cheaper PMBJP generic-equivalent, if the ingredient is in "
        "the (small, curated) seed dataset. Null does not mean unavailable in "
        "real life, only that this demo dataset doesn't cover it.",
    )


class PrescriptionMedicine(BaseModel):
    """Trimmed medicine view embedded in a prescription detail response.

    A separate type from :class:`MedicineResponse` on purpose: the confirmation
    review UI wants a compact list, and exposing internal ``updated_at`` churn
    in a nested object is noise.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_name: str
    normalized_ingredient: str | None
    brand_name: str | None
    strength: str | None
    dose: str | None
    frequency: str | None
    duration: str | None
    confidence_score: float | None
    is_confirmed: bool
    status: MedicineStatus


class MedicineConfirmRequest(BaseModel):
    """Edit-and-confirm in a single call.

    Every field is optional: the user may confirm an OCR line untouched, correct
    one field, or correct several at once. Only the supplied fields change,
    which keeps the "correct exactly one thing a nurse misread" case from
    blanking the fields the extractor got right.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    raw_name: str | None = Field(default=None, min_length=1, max_length=255)
    brand_name: str | None = Field(default=None, max_length=255)
    strength: str | None = Field(default=None, max_length=100)
    dose: str | None = Field(default=None, max_length=100)
    frequency: str | None = Field(default=None, max_length=100)
    duration: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _at_least_one_edit(self) -> MedicineConfirmRequest:
        """Require an actual edit, or reject an empty body.

        ``PATCH`` with ``{}`` is almost always a client bug, and silently
        confirming the unreviewed values would let a mis-wired button push bad
        data past the review step that exists to catch exactly that.
        """
        edits = self.model_dump(exclude_none=True)
        if not edits:
            raise ValueError(
                "supply at least one field to correct, e.g. raw_name or strength"
            )
        return self


class MedicineRejectRequest(BaseModel):
    """Dismiss an extracted line that is not a real medicine."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    reason: str | None = Field(
        default=None,
        max_length=500,
        description="Optional note. Kept in the audit log, not on the medicine row.",
    )


class ManualMedicineRequest(BaseModel):
    """A hand-typed medicine. Confirmed by definition.

    There is nothing to review when the user types the drug themselves, so the
    row is created confirmed and immediately eligible for duplicate detection.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    raw_name: str = Field(
        min_length=1,
        max_length=255,
        description=(
            "What the user typed. Run through the same normaliser as OCR output."
        ),
    )
    brand_name: str | None = Field(default=None, max_length=255)
    strength: str | None = Field(default=None, max_length=100)
    dose: str | None = Field(default=None, max_length=100)
    frequency: str | None = Field(default=None, max_length=100)
    duration: str | None = Field(default=None, max_length=100)
    status: MedicineStatus = Field(
        default=MedicineStatus.ACTIVE,
        description=(
            "ACTIVE unless the user is recording a finished course, in which "
            "case DISCONTINUED. REJECTED is not accepted here."
        ),
    )

    @model_validator(mode="after")
    def _no_rejected_status(self) -> ManualMedicineRequest:
        if self.status is MedicineStatus.REJECTED:
            raise ValueError(
                "status must be 'active' or 'discontinued'; a rejected row is "
                "produced by rejecting an extracted line, not by typing one"
            )
        return self


class DuplicateFlagResponse(BaseModel):
    """A suspected duplicate pair, with both medicines expanded."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    medicine_a: MedicineResponse
    medicine_b: MedicineResponse
    detected_at: datetime
    resolved: bool
    resolved_at: datetime | None
    resolution: str | None = Field(
        default=None, description="How it was resolved, if it was."
    )


class DuplicateResolveRequest(BaseModel):
    """Dismiss or merge a suspected duplicate.

    The three choices map to the three real-world answers:

    * ``keep_both`` -- genuinely different despite a shared ingredient (two
      strengths, or a combination product). Nothing is deleted.
    * ``merged`` -- the same drug entered twice. ``kept_medicine_id`` names the
      survivor and the other is tombstoned.
    * ``not_a_duplicate`` -- the detector was simply wrong. Same effect on the
      data as ``keep_both``, recorded differently so the flag is not
      re-raised identically forever.
    """

    model_config = ConfigDict(extra="forbid")

    resolution: Literal["keep_both", "merged", "not_a_duplicate"]
    kept_medicine_id: int | None = Field(
        default=None,
        description="Required for 'merged': the id of the row to keep.",
    )
    note: str | None = Field(default=None, max_length=500)


class DuplicateResolveResponse(BaseModel):
    """Outcome of resolving a duplicate flag."""

    id: int
    resolved: bool
    resolved_at: datetime
    resolution: str
    kept_medicine_id: int | None = Field(
        default=None, description="Null unless 'merged' removed a row."
    )
    removed_medicine_id: int | None = Field(
        default=None, description="The row tombstoned by a 'merged' resolution."
    )
