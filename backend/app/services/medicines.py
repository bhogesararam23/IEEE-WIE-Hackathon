"""Medicine list: OCR ingestion, review confirmation, rejection, manual entry.

The lifecycle has three states and the transitions between them are the whole
point of this module:

* **unconfirmed** -- an extraction proposal. Excluded from every list a safety
  check would read, because a misread drug name is a false clinical signal.
* **confirmed** -- the user has seen it and vouched for it. Normalised, and
  eligible for duplicate detection.
* **rejected** -- the user looked at it and said it is not one of their drugs.
  Kept on the prescription for provenance, excluded from the list.

Rejection sets ``status`` rather than deleting. Deleting would make the audit
log the only record that the proposal ever existed, and re-running OCR on the
same document would re-add it with no way for the user to say "not this one
again".
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MedicineStatus
from app.models.medicine import DuplicateFlag, Medicine
from app.models.prescription import Prescription
from app.schemas.medicine import (
    ManualMedicineRequest,
    MedicineConfirmRequest,
    MedicineRejectRequest,
)
from app.schemas.prescription import OcrMedicineResult
from app.services import reconcile
from app.services.brand_map import normalize_medicine

logger = logging.getLogger(__name__)

__all__ = [
    "MedicineAccessError",
    "MedicineStateError",
    "add_manual_medicine",
    "confirm_medicine",
    "count_pending_review",
    "get_medicine",
    "ingest_ocr_results",
    "list_medicines",
    "mock_ocr_results",
    "reject_medicine",
]

# Fields a user may correct during review, and which the confirming user is
# allowed to overwrite. Mirrors MedicineConfirmRequest; kept as a tuple so the
# apply loop and the schema cannot drift apart silently.
_EDITABLE_FIELDS = (
    "raw_name",
    "brand_name",
    "strength",
    "dose",
    "frequency",
    "duration",
)


class MedicineAccessError(LookupError):
    """The medicine does not exist, or is not the caller's."""


class MedicineStateError(ValueError):
    """The requested transition is not valid from the row's current state."""


async def get_medicine(
    session: AsyncSession, *, user_id: int, medicine_id: int
) -> Medicine:
    """Load one medicine owned by ``user_id``, or raise.

    Scoped in the query so another user's row is simply not found -- confirming
    or rejecting someone else's row must be impossible, not merely unauthorised.
    """
    medicine = await session.scalar(
        select(Medicine).where(Medicine.id == medicine_id, Medicine.user_id == user_id)
    )
    if medicine is None:
        raise MedicineAccessError(f"medicine {medicine_id} not found")
    return medicine


async def ingest_ocr_results(
    session: AsyncSession,
    *,
    user_id: int,
    prescription: Prescription,
    results: list[OcrMedicineResult],
    extractor: str | None = None,
) -> list[Medicine]:
    """Store extraction proposals against a prescription, all unconfirmed.

    Rows are created, never updated. A re-run of OCR on the same document
    therefore produces a fresh, still-unconfirmed batch rather than silently
    overwriting edits the user has already made to a previous one -- if an
    extractor improves, the user re-reviews, and their existing confirmations are
    never lost behind it.

    Returns the created rows. Nothing is normalised here on purpose: a
    normalisation guess is only trustworthy once a human has agreed to it, so
    ``normalized_ingredient`` stays null until :func:`confirm_medicine`.
    """
    if prescription.user_id != user_id:  # pragma: no cover - router checks first
        raise MedicineAccessError(f"prescription {prescription.id} not found")

    rows = [
        Medicine(
            user_id=user_id,
            prescription_id=prescription.id,
            raw_name=item.raw_name,
            brand_name=item.brand_name,
            strength=item.strength,
            dose=item.dose,
            frequency=item.frequency,
            duration=item.duration,
            confidence_score=item.confidence,
            is_confirmed=False,
            status=MedicineStatus.ACTIVE,
        )
        for item in results
    ]
    session.add_all(rows)
    await session.flush()
    logger.info(
        "Stored %d OCR proposal(s) for prescription %s (extractor=%s)",
        len(rows),
        prescription.id,
        extractor or "unspecified",
    )
    return rows


def mock_ocr_results(prescription: Prescription) -> list[OcrMedicineResult]:
    """Deterministic fake extraction, for development and for the e2e walkthrough.

    Fixed content rather than random so the same document always produces the
    same proposals, which makes the reconciliation test reproducible: the two
    Paracetamol lines are *meant* to collide, and a random draw would sometimes
    produce a duplicate and sometimes not.

    Includes one line with no mapping (``"Herbal Liver Tonic"``) so the
    "extracts cleanly, still does not match" path is exercised rather than only
    the happy path.
    """
    return [
        OcrMedicineResult(
            raw_name="Crocin 500mg",
            brand_name="Crocin",
            strength="500mg",
            dose="1 tablet",
            frequency="twice daily",
            duration="5 days",
            confidence=0.94,
        ),
        OcrMedicineResult(
            raw_name="Dolo 650",
            brand_name="Dolo",
            strength="650mg",
            dose="1 tablet",
            frequency="three times daily",
            duration="3 days",
            confidence=0.88,
        ),
        OcrMedicineResult(
            raw_name="Herbal Liver Tonic",
            brand_name=None,
            strength=None,
            dose="2 spoons",
            frequency="twice daily",
            duration=None,
            confidence=0.41,
        ),
    ]


async def confirm_medicine(
    session: AsyncSession,
    *,
    user_id: int,
    medicine_id: int,
    edits: MedicineConfirmRequest,
) -> tuple[Medicine, list[DuplicateFlag]]:
    """Apply the user's corrections, confirm the row, and check for duplicates.

    Returns ``(medicine, new_duplicate_flags)``.

    The ordering is load-edit-normalise-flag, and each step depends on the one
    before it: corrections must land first so normalisation runs on what the
    *user* said rather than what the extractor said, and normalisation must
    produce an ingredient before there is anything to compare.

    ``confidence_score`` is cleared on confirmation. It described how sure the
    extractor was; keeping it beside a row the user has vouched for invites a
    reader to treat "0.41" as meaningful about a confirmed drug when it is not.
    """
    medicine = await get_medicine(session, user_id=user_id, medicine_id=medicine_id)

    if medicine.status is MedicineStatus.REJECTED:
        raise MedicineStateError(
            "this line was already rejected; upload the document again if it is "
            "really one of your medicines"
        )

    for field in _EDITABLE_FIELDS:
        value = getattr(edits, field, None)
        if value is not None:
            setattr(medicine, field, value)

    # Normalise on the post-edit values. Falls back to the brand name when the
    # raw name is uninformative, and then to nothing: an unmatched drug keeps a
    # null ingredient rather than a guess.
    result = normalize_medicine(medicine.raw_name, medicine.strength)
    if not result.matched and medicine.brand_name:
        result = normalize_medicine(medicine.brand_name, medicine.strength)

    if result.matched:
        medicine.normalized_ingredient = result.ingredient
        if not medicine.brand_name and result.matched_brand:
            medicine.brand_name = result.matched_brand
    else:
        medicine.normalized_ingredient = None
        logger.info(
            "No brand mapping for medicine %s (%r); left unnormalised",
            medicine.id,
            medicine.raw_name,
        )

    medicine.is_confirmed = True
    medicine.confidence_score = None
    if medicine.status is not MedicineStatus.ACTIVE:
        # A discontinued course being confirmed is a correction, not a new drug.
        medicine.status = MedicineStatus.ACTIVE
    await session.flush()

    flags = await reconcile.flag_duplicates_for(session, medicine=medicine)
    return medicine, flags


async def reject_medicine(
    session: AsyncSession,
    *,
    user_id: int,
    medicine_id: int,
    payload: MedicineRejectRequest,
) -> Medicine:
    """Dismiss an extracted line. The row stays, hidden from the list.

    Any duplicate flags that referenced this proposal are tombstoned: the
    proposal was never trusted, so a flag built on it was never meaningful.
    """
    medicine = await get_medicine(session, user_id=user_id, medicine_id=medicine_id)
    now = datetime.now(UTC)

    medicine.status = MedicineStatus.REJECTED
    # Explicitly false rather than left as-is: a rejected line must not be
    # readable as "confirmed" by any query that only checks is_confirmed.
    medicine.is_confirmed = False
    # A bulk UPDATE rather than ORM loads: the global soft-delete filter exempts
    # non-SELECT statements by design, which is what lets this reach flags whose
    # medicines are already hidden.
    await session.execute(
        update(DuplicateFlag)
        .where(
            or_(
                DuplicateFlag.medicine_id_a == medicine.id,
                DuplicateFlag.medicine_id_b == medicine.id,
            ),
            DuplicateFlag.resolved.is_(False),
        )
        .values(deleted_at=now, resolved=True, resolved_at=now)
    )
    await session.flush()
    logger.info(
        "Rejected OCR proposal medicine=%s reason=%r", medicine.id, payload.reason
    )
    return medicine


async def add_manual_medicine(
    session: AsyncSession,
    *,
    user_id: int,
    payload: ManualMedicineRequest,
) -> tuple[Medicine, list[DuplicateFlag]]:
    """Add a hand-typed medicine, confirmed on creation.

    Typed by the user, so there is nothing to review -- but it is still run
    through the same normaliser, because a manually typed "Dolo 650" has to land
    on the same ingredient as an OCR'd one for duplicate detection to see them.
    """
    result = normalize_medicine(payload.raw_name, payload.strength)
    if not result.matched and payload.brand_name:
        result = normalize_medicine(payload.brand_name, payload.strength)

    medicine = Medicine(
        user_id=user_id,
        prescription_id=None,
        raw_name=payload.raw_name,
        brand_name=payload.brand_name
        or (result.matched_brand if result.matched else None),
        strength=payload.strength or (result.strength if result.matched else None),
        dose=payload.dose,
        frequency=payload.frequency,
        duration=payload.duration,
        normalized_ingredient=result.ingredient if result.matched else None,
        is_confirmed=True,
        status=payload.status,
        confidence_score=None,
    )
    session.add(medicine)
    await session.flush()

    flags = await reconcile.flag_duplicates_for(session, medicine=medicine)
    return medicine, flags


async def list_medicines(
    session: AsyncSession,
    *,
    user_id: int,
    status: MedicineStatus | None = None,
    confirmed: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Medicine], int]:
    """Return a page of the caller's medicines, newest first, plus the total.

    Filters are optional and compose. The default -- no status filter, no
    confirmed filter -- returns everything the user owns, which is what the
    review UI wants. Safety-checking callers should pass
    ``confirmed=True, status=ACTIVE``, since an unconfirmed OCR line is not a
    drug the user takes.
    """
    conditions = [Medicine.user_id == user_id]
    if status is not None:
        conditions.append(Medicine.status == status)
    if confirmed is not None:
        conditions.append(Medicine.is_confirmed.is_(confirmed))

    total = await session.scalar(
        select(func.count()).select_from(Medicine).where(*conditions)
    )
    rows = list(
        (
            await session.scalars(
                select(Medicine)
                .where(*conditions)
                .order_by(Medicine.created_at.desc(), Medicine.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return rows, int(total or 0)


async def count_pending_review(session: AsyncSession, *, user_id: int) -> int:
    """How many extracted lines are waiting for the user to accept or dismiss."""
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Medicine)
            .where(
                Medicine.user_id == user_id,
                ~Medicine.is_confirmed,
                Medicine.status != MedicineStatus.REJECTED,
            )
        )
        or 0
    )


async def list_pending_review(session: AsyncSession, *, user_id: int) -> list[Medicine]:
    """Every unconfirmed, unrejected medicine, oldest first.

    Oldest first on purpose: the review queue is a to-do list, and the oldest
    proposal is the one most likely to be forgotten until it is still useful.
    """
    return list(
        (
            await session.scalars(
                select(Medicine)
                .where(
                    Medicine.user_id == user_id,
                    ~Medicine.is_confirmed,
                    Medicine.status != MedicineStatus.REJECTED,
                )
                .order_by(Medicine.created_at.asc(), Medicine.id.asc())
            )
        ).all()
    )
