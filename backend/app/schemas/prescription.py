"""Schemas for prescription upload, listing, and OCR ingestion."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MedicineSourceType, PrescriptionFileType
from app.schemas.medicine import PrescriptionMedicine

__all__ = [
    "OcrIngestRequest",
    "OcrMedicineResult",
    "PrescriptionDetailResponse",
    "PrescriptionListResponse",
    "PrescriptionResponse",
]


class OcrMedicineResult(BaseModel):
    """One medicine line as the extraction stage proposes it.

    A *proposal*, not a fact. Everything here is a string because an OCR model
    has no notion of a normalised ingredient, and the whole point of the review
    step is that the user corrects these fields before anything downstream trusts
    them.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    raw_name: str = Field(
        min_length=1,
        max_length=255,
        description="Verbatim text the extractor read off the document.",
    )
    brand_name: str | None = Field(default=None, max_length=255)
    strength: str | None = Field(
        default=None,
        max_length=100,
        description="Dose strength, e.g. '500mg'. Preserved verbatim from OCR.",
    )
    dose: str | None = Field(
        default=None,
        max_length=100,
        description="Amount per administration, e.g. '1 tablet'.",
    )
    frequency: str | None = Field(
        default=None, max_length=100, description="How often, e.g. 'twice daily'."
    )
    duration: str | None = Field(
        default=None, max_length=100, description="Course length, e.g. '5 days'."
    )
    # 0..1 to match the medicines_confidence_score CHECK constraint. Nullable
    # because a self-hosted extractor may genuinely not report a score, and
    # inventing 0.0 would look like real certainty.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class OcrIngestRequest(BaseModel):
    """Body for posting extraction results onto an existing prescription."""

    model_config = ConfigDict(extra="forbid")

    medicines: list[OcrMedicineResult] = Field(
        min_length=1,
        max_length=50,
        description="Extracted medicine lines. Kept alongside any earlier batch.",
    )
    # Recorded in the audit log so an operator can tell which engine produced a
    # bad batch and reproduce the problem. Not stored on the row: the
    # prescription's own source_type is what the user's list needs.
    extractor: str | None = Field(
        default=None,
        max_length=64,
        description="Engine identifier, e.g. 'google-vision'.",
    )


class PrescriptionResponse(BaseModel):
    """One upload, without its medicines."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    file_url: str = Field(description="Relative URL of the stored file, under /files.")
    file_type: PrescriptionFileType
    uploaded_at: datetime
    source_type: MedicineSourceType
    medicine_count: int = Field(
        default=0,
        description="Medicines currently attached and not soft-deleted.",
    )
    pending_review_count: int = Field(
        default=0,
        description="Attached medicines still awaiting the user's confirmation.",
    )


class PrescriptionDetailResponse(PrescriptionResponse):
    """One upload together with every medicine extracted from it."""

    medicines: list[PrescriptionMedicine] = Field(default_factory=list)


class PrescriptionListResponse(BaseModel):
    """Paginated envelope for ``GET /prescriptions``.

    Wrapped rather than returned as a bare array so that ``total`` can be added
    later without breaking existing clients.
    """

    items: list[PrescriptionResponse]
    total: int = Field(
        description="Total uploads owned by the caller, ignoring pagination."
    )
