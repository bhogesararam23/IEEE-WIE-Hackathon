"""Prescription upload, retrieval, and OCR ingestion endpoints.

Upload is a ``multipart/form-data`` POST rather than JSON with a base64 payload:
base64 inflates the body by a third before the size cap applies, and the whole
point of the 10 MB limit is to bound memory, so the bytes should never be
inflated in the first place.
"""

from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from app.core.deps import CurrentUser, DbSession, client_ip
from app.models.enums import MedicineSourceType, MedicineStatus
from app.schemas.prescription import (
    OcrIngestRequest,
    PrescriptionDetailResponse,
    PrescriptionListResponse,
    PrescriptionResponse,
)
from app.services import medicines as medicines_service
from app.services import prescriptions as prescriptions_service
from app.services.audit import AuditAction, record
from app.services.storage import StorageError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prescriptions", tags=["prescriptions"])


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


async def _audit_rejected_upload(  # noqa: ANN001
    session, request, user_id: int, submitted_name: str | None
) -> None:
    """Record a refused upload.

    No prescription row exists, so there is no id to point at -- and
    ``audit_logs.resource_id`` is NOT NULL on purpose, because an audit row that
    does not say what it refers to is close to useless. The submitted filename is
    the most useful identifier available at that point, and it is worth keeping:
    "someone tried to upload payload.sh" is exactly the fact a reviewer wants.
    It is truncated to the column width and is never used as a path.
    """
    await record(
        session,
        action=AuditAction.PRESCRIPTION_REJECTED_UPLOAD,
        resource_type="prescription_upload",
        resource_id=(submitted_name or "unknown")[:64],
        user_id=user_id,
        ip_address=client_ip(request),
    )
    await session.commit()


@router.post(
    "/upload",
    response_model=PrescriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a prescription image or PDF",
    responses={
        201: {"description": "Stored; returns the created prescription."},
        401: {"description": "Not authenticated."},
        413: {"description": "File exceeds the configured upload limit."},
        415: {"description": "Content is not a recognised image or PDF."},
    },
)
async def upload_prescription(
    request: Request,
    user: CurrentUser,
    session: DbSession,
    file: UploadFile = File(..., description="JPEG, PNG, GIF, BMP, TIFF, WebP or PDF."),
    source_type: MedicineSourceType = Form(
        default=MedicineSourceType.PRESCRIPTION,
        description="How this document relates to the user's medication list.",
    ),
) -> PrescriptionResponse:
    """Store a prescription and register it.

    The type is decided by inspecting the bytes, so renaming a ``.txt`` to
    ``.jpg`` does not get past the check, and neither does a request that lies in
    its ``Content-Type``.

    The response's ``file_url`` is relative (``/files/prescriptions/...``). Note
    that this static mount is unauthenticated: anyone who knows or guesses the
    UUID can fetch the image. That is a known trade-off of serving files
    directly, called out here because it is not visible in the response shape.
    Presigned URLs, or an authenticated file endpoint, is the fix if these
    uploads are ever anything other than demo data.
    """
    try:
        prescription = await prescriptions_service.create_upload(
            session, user_id=user.id, upload=file, source_type=source_type
        )
    except prescriptions_service.UploadTooLargeError as exc:
        await _audit_rejected_upload(session, request, user.id, file.filename)
        raise HTTPException(
            # Named ..._ENTITY_TOO_LARGE, not ..._CONTENT_TOO_LARGE: the latter
            # is the newer RFC 9110 spelling and is absent from Starlette 0.41.
            # The status code is identical either way.
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except prescriptions_service.UnsupportedFileTypeError as exc:
        await _audit_rejected_upload(session, request, user.id, file.filename)
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except StorageError as exc:
        # A full disk or a permissions problem is ours, not the caller's, and the
        # 5xx keeps it distinguishable from the 4xx validation failures above.
        logger.exception("Upload storage failure for user %s", user.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="could not store the upload",
        ) from exc

    await record(
        session,
        action=AuditAction.PRESCRIPTION_UPLOADED,
        resource_type="prescription",
        resource_id=prescription.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return PrescriptionResponse.model_validate(prescription)


@router.get(
    "",
    response_model=PrescriptionListResponse,
    summary="List the caller's prescription uploads",
    responses={401: {"description": "Not authenticated."}},
)
async def list_prescriptions(
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PrescriptionListResponse:
    """Return the caller's uploads, newest first.

    Owner-scoped by construction -- the query filters on ``user_id`` from the
    token, so there is no parameter through which one user could ask for
    another's documents.
    """
    rows, total = await prescriptions_service.list_prescriptions(
        session, user_id=user.id, limit=limit, offset=offset
    )
    counts = await prescriptions_service.medicine_counts(
        session, prescription_ids=[row.id for row in rows]
    )
    items = []
    for row in rows:
        total_meds, pending = counts.get(row.id, (0, 0))
        items.append(
            PrescriptionResponse(
                id=row.id,
                file_url=row.file_url,
                file_type=row.file_type,
                uploaded_at=row.uploaded_at,
                source_type=row.source_type,
                medicine_count=total_meds,
                pending_review_count=pending,
            )
        )
    return PrescriptionListResponse(items=items, total=total)


@router.get(
    "/{prescription_id}",
    response_model=PrescriptionDetailResponse,
    summary="Fetch one upload with its extracted medicines",
    responses={
        200: {"description": "The prescription and its medicines."},
        401: {"description": "Not authenticated."},
        404: {"description": "No such prescription, or it is not the caller's."},
    },
)
async def get_prescription(
    prescription_id: int,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> PrescriptionDetailResponse:
    """Return one upload together with every medicine extracted from it.

    404 rather than 403 for another user's id, so the endpoint does not confirm
    that a prescription id exists.
    """
    try:
        prescription = await prescriptions_service.get_prescription_with_medicines(
            session, user_id=user.id, prescription_id=prescription_id
        )
    except prescriptions_service.PrescriptionAccessError as exc:
        raise _not_found(str(exc)) from exc

    await record(
        session,
        action=AuditAction.PRESCRIPTION_READ,
        resource_type="prescription",
        resource_id=prescription.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return _detail(prescription)


@router.delete(
    "/{prescription_id}",
    response_model=PrescriptionResponse,
    summary="Delete a prescription and its file",
    responses={
        200: {"description": "Tombstoned; the stored file has been removed."},
        401: {"description": "Not authenticated."},
        404: {"description": "No such prescription, or it is not the caller's."},
    },
)
async def delete_prescription(
    prescription_id: int,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> PrescriptionResponse:
    """Remove an upload.

    Deletes the row's visibility *and* the file on disk: the row is tombstoned
    per the app-wide retention rule, while the file is genuinely removed, since
    leaving a 10 MB blob behind is not what "delete" means to the user pressing
    the button. The response still describes the row, which is how the caller can
    tell a delete succeeded even though the resource is now unreadable.
    """
    try:
        prescription, _count = await prescriptions_service.delete_prescription(
            session, user_id=user.id, prescription_id=prescription_id
        )
    except prescriptions_service.PrescriptionAccessError as exc:
        raise _not_found(str(exc)) from exc

    await record(
        session,
        action=AuditAction.PRESCRIPTION_DELETED,
        resource_type="prescription",
        resource_id=prescription.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return PrescriptionResponse(
        id=prescription.id,
        file_url=prescription.file_url,
        file_type=prescription.file_type,
        uploaded_at=prescription.uploaded_at,
        source_type=prescription.source_type,
        medicine_count=0,
        pending_review_count=0,
    )


@router.post(
    "/{prescription_id}/ocr-results",
    response_model=PrescriptionDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record extraction results against an upload",
    responses={
        201: {"description": "Proposals stored, all unconfirmed."},
        401: {"description": "Not authenticated."},
        404: {"description": "No such prescription, or it is not the caller's."},
    },
)
async def post_ocr_results(
    prescription_id: int,
    payload: OcrIngestRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> PrescriptionDetailResponse:
    """Store proposed medicines for a user to review.

    The caller is the extraction service, not the end user, so this endpoint is
    the ingestion point. It creates new unconfirmed rows rather than updating
    existing ones, so a re-run never discards confirmations the user already
    made on an earlier batch.
    """
    try:
        prescription = await prescriptions_service.get_prescription_with_medicines(
            session, user_id=user.id, prescription_id=prescription_id
        )
    except prescriptions_service.PrescriptionAccessError as exc:
        raise _not_found(str(exc)) from exc

    await medicines_service.ingest_ocr_results(
        session,
        user_id=user.id,
        prescription=prescription,
        results=payload.medicines,
        extractor=payload.extractor,
    )
    await record(
        session,
        action=AuditAction.OCR_RESULTS_RECORDED,
        resource_type="prescription",
        resource_id=prescription.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    await session.refresh(prescription)

    return _detail(prescription)


@router.post(
    "/{prescription_id}/mock-ocr",
    response_model=PrescriptionDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Seed deterministic fake extraction results (development only)",
    responses={
        201: {"description": "Mock proposals stored, all unconfirmed."},
        401: {"description": "Not authenticated."},
        404: {"description": "No such prescription, or it is not the caller's."},
    },
)
async def post_mock_ocr(
    prescription_id: int,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> PrescriptionDetailResponse:
    """Insert three fixed medicines as if an OCR engine had read the document.

    There is no real OCR here on purpose -- the point is to exercise everything
    downstream of extraction: the review queue, confirmation, normalisation, and
    duplicate detection. Two of the three seeded lines are different brands of the
    same ingredient, so the reconciliation path runs for real.

    Intended for development and the end-to-end walkthrough. In a deployment this
    should be gated by a feature flag or removed, since anyone with a token could
    otherwise fill a prescription with fabricated medicines.
    """
    try:
        prescription = await prescriptions_service.get_prescription_with_medicines(
            session, user_id=user.id, prescription_id=prescription_id
        )
    except prescriptions_service.PrescriptionAccessError as exc:
        raise _not_found(str(exc)) from exc

    await medicines_service.ingest_ocr_results(
        session,
        user_id=user.id,
        prescription=prescription,
        results=medicines_service.mock_ocr_results(prescription),
        extractor="mock",
    )
    await record(
        session,
        action=AuditAction.OCR_RESULTS_RECORDED,
        resource_type="prescription",
        resource_id=prescription.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    await session.refresh(prescription)

    return _detail(prescription)


def _detail(prescription) -> PrescriptionDetailResponse:  # noqa: ANN001 - ORM row
    """Build a detail response from a loaded prescription, with its medicines.

    ``status`` is compared as an enum rather than a string literal so a new
    non-active status cannot silently fall through into "pending review".
    """
    pending = sum(
        1
        for m in prescription.medicines
        if not m.is_confirmed and m.status is not MedicineStatus.REJECTED
    )
    return PrescriptionDetailResponse(
        id=prescription.id,
        file_url=prescription.file_url,
        file_type=prescription.file_type,
        uploaded_at=prescription.uploaded_at,
        source_type=prescription.source_type,
        medicine_count=len(prescription.medicines),
        pending_review_count=pending,
        medicines=sorted(prescription.medicines, key=lambda m: m.id),
    )
