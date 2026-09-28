"""Prescription upload, listing, and deletion.

Upload is the only place in the app that writes a file, so the validation order
matters: size, then content, then disk, then database. Each step is cheaper to
undo than the one after it, and the two failure modes that matter -- an oversized
body and an unrecognised file -- are both caught before anything is persisted.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.soft_delete import soft_delete_prescription
from app.models.enums import MedicineSourceType, MedicineStatus
from app.models.medicine import Medicine
from app.models.prescription import Prescription
from app.services.storage import (
    StorageError,
    StorageService,
    get_storage_service,
    sniff_image_type,
)

logger = logging.getLogger(__name__)

__all__ = [
    "PrescriptionAccessError",
    "UnsupportedFileTypeError",
    "UploadTooLargeError",
    "count_prescriptions",
    "create_upload",
    "delete_prescription",
    "get_prescription",
    "get_prescription_with_medicines",
    "list_prescriptions",
]

# 64 KiB: large enough that a 10 MiB upload needs ~160 reads, small enough that
# the request object is not held in memory in one giant buffer.
_CHUNK = 64 * 1024


class UploadTooLargeError(ValueError):
    """The body exceeded ``Settings.max_upload_bytes``."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"file exceeds the {limit // (1024 * 1024)} MB upload limit")
        self.limit = limit


class UnsupportedFileTypeError(ValueError):
    """The bytes are neither a recognised image nor a PDF."""


class PrescriptionAccessError(LookupError):
    """The prescription does not exist, or is not the caller's.

    One error for both cases on purpose: distinguishing them would let a caller
    probe which prescription ids exist in the system.
    """


async def _read_capped(upload: UploadFile, limit: int) -> bytes:
    """Read the upload into memory, refusing to exceed ``limit`` bytes.

    Checked while reading rather than against the ``Content-Length`` header,
    because that header is client-supplied and a 10 GB body claiming
    ``Content-Length: 12`` would otherwise be buffered before we noticed.
    Aborting mid-stream also means we never hold more than the limit plus one
    chunk.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise UploadTooLargeError(limit)
        chunks.append(chunk)
    return b"".join(chunks)


async def create_upload(
    session: AsyncSession,
    *,
    user_id: int,
    upload: UploadFile,
    source_type: MedicineSourceType = MedicineSourceType.PRESCRIPTION,
    storage: StorageService | None = None,
) -> Prescription:
    """Validate, store, and register one uploaded prescription.

    Raises :class:`UploadTooLargeError` or :class:`UnsupportedFileTypeError` with
    nothing written, and :class:`~app.services.storage.StorageError` if the
    filesystem write fails. On any failure after the file lands on disk the file
    is removed again, so a rolled-back request does not leak an orphan.

    The file type is decided by the bytes, not by ``upload.content_type`` or the
    submitted filename. Both are attacker-controlled, and both end up deciding
    how a browser renders a URL we serve back.
    """
    settings = get_settings()
    backend = storage or get_storage_service()

    data = await _read_capped(upload, settings.max_upload_bytes)
    if not data:
        raise UnsupportedFileTypeError("file is empty")

    sniffed = sniff_image_type(data)
    if sniffed is None:
        raise UnsupportedFileTypeError(
            "unsupported file type: upload a JPEG, PNG, GIF, BMP, TIFF, WebP " "or PDF"
        )
    file_type, extension = sniffed

    stored = await backend.save(user_id=user_id, data=data, extension=extension)
    try:
        prescription = Prescription(
            user_id=user_id,
            file_url=stored.url,
            storage_key=stored.key,
            file_type=file_type,
            uploaded_at=datetime.now(UTC),
            source_type=source_type,
        )
        session.add(prescription)
        await session.flush()
    except Exception:
        # The row did not stick, so neither should the bytes. Best-effort: the
        # original error is the one worth surfacing.
        try:
            await backend.delete(stored.key)
        except StorageError:  # pragma: no cover - cleanup is best-effort
            logger.exception("Could not remove orphaned upload %s", stored.key)
        raise

    logger.info(
        "Prescription %s stored for user %s (%s, %d bytes)",
        prescription.id,
        user_id,
        file_type.value,
        stored.size,
    )
    return prescription


async def get_prescription(
    session: AsyncSession, *, user_id: int, prescription_id: int
) -> Prescription:
    """Load one prescription owned by ``user_id``.

    Scoped by ``user_id`` in the query rather than checked afterwards, so another
    user's row is simply not found. A ``select()`` rather than ``session.get()``
    because the global soft-delete loader criteria do not apply to the
    identity-map path.
    """
    prescription = await session.scalar(
        select(Prescription).where(
            Prescription.id == prescription_id, Prescription.user_id == user_id
        )
    )
    if prescription is None:
        raise PrescriptionAccessError(f"prescription {prescription_id} not found")
    return prescription


async def get_prescription_with_medicines(
    session: AsyncSession, *, user_id: int, prescription_id: int
) -> Prescription:
    """As :func:`get_prescription`, with medicines eagerly loaded.

    ``selectinload`` rather than lazy access: touching ``prescription.medicines``
    outside this await raises ``MissingGreenlet`` under async. The global filter
    also covers the second query, so tombstoned medicines are excluded here too.
    """
    prescription = await session.scalar(
        select(Prescription)
        .options(selectinload(Prescription.medicines))
        .where(Prescription.id == prescription_id, Prescription.user_id == user_id)
    )
    if prescription is None:
        raise PrescriptionAccessError(f"prescription {prescription_id} not found")
    return prescription


async def list_prescriptions(
    session: AsyncSession, *, user_id: int, limit: int, offset: int
) -> tuple[list[Prescription], int]:
    """Return one page of the caller's uploads, newest first, plus the total.

    Medicines are not eagerly loaded; the counts for the response are gathered
    by :func:`medicine_counts` in a single grouped query rather than by touching
    each row's collection, which would be one extra round-trip per prescription.
    """
    total = await count_prescriptions(session, user_id=user_id)
    rows = list(
        (
            await session.scalars(
                select(Prescription)
                .where(Prescription.user_id == user_id)
                .order_by(Prescription.uploaded_at.desc(), Prescription.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return rows, total


async def count_prescriptions(session: AsyncSession, *, user_id: int) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(Prescription)
        .where(Prescription.user_id == user_id)
    )


async def medicine_counts(
    session: AsyncSession, *, prescription_ids: list[int]
) -> dict[int, tuple[int, int]]:
    """Map ``prescription_id -> (total, pending_review)`` for the given ids.

    One grouped query for the whole page. ``pending_review`` counts rows that
    are neither confirmed nor rejected, which is what the review badge shows.
    Rejected rows stay attached to the prescription for provenance but must not
    keep appearing as "awaiting review" forever.
    """
    if not prescription_ids:
        return {}

    total = func.count(Medicine.id)
    pending = func.count(Medicine.id).filter(
        ~Medicine.is_confirmed, Medicine.status != MedicineStatus.REJECTED
    )
    rows = (
        await session.execute(
            select(Medicine.prescription_id, total, pending)
            .where(Medicine.prescription_id.in_(prescription_ids))
            .group_by(Medicine.prescription_id)
        )
    ).all()
    return {pid: (int(total_), int(pending_)) for pid, total_, pending_ in rows}


async def delete_prescription(
    session: AsyncSession,
    *,
    user_id: int,
    prescription_id: int,
    storage: StorageService | None = None,
) -> tuple[Prescription, int]:
    """Tombstone a prescription and remove its file. Returns ``(row, n_medicines)``.

    The row is soft-deleted, the file is physically removed. That is a deliberate
    split: the DB side has to follow the retention rule the rest of the app
    follows, while the file side is what "deletes the file from storage" means
    and a tombstoned row pointing at a 10 MB blob is not much of a deletion.

    The consequence, stated plainly because it surprises people: restoring a
    prescription from the tombstone would give back a row whose file is gone.
    Until a retention-and-restore path exists, treat these rows as terminal.
    """
    prescription = await get_prescription(
        session, user_id=user_id, prescription_id=prescription_id
    )
    storage_key = prescription.storage_key
    now = datetime.now(UTC)

    count = await soft_delete_prescription(
        session, prescription=prescription, deleted_at=now
    )

    # Commit order matters and is why the caller commits after this returns: the
    # tombstone should be durable even if the unlink fails, otherwise a retried
    # delete would find a live row and a missing file.
    await session.commit()

    backend = storage or get_storage_service()
    try:
        await backend.delete(storage_key)
    except StorageError:
        # Logged, not raised. The row is already gone as far as the API is
        # concerned, and reporting a 500 here would invite a retry storm against
        # an operation that has already effectively succeeded. The orphan file is
        # a storage-hygiene problem, not an API correctness one.
        logger.exception(
            "Prescription %s tombstoned but its file %s could not be removed",
            prescription_id,
            storage_key,
        )

    return prescription, count
