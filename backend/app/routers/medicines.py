"""Medicine list, review actions, and duplicate resolution endpoints.

The literal paths (``/pending-review``, ``/duplicates``) are declared before any
parameterised sibling. FastAPI matches in declaration order, so this is what
keeps a literal segment from being swallowed by a ``{medicine_id}`` parameter.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.deps import CurrentUser, DbSession, client_ip
from app.models.enums import MedicineStatus
from app.schemas.medicine import (
    DuplicateFlagResponse,
    DuplicateResolveRequest,
    DuplicateResolveResponse,
    ManualMedicineRequest,
    MedicineConfirmRequest,
    MedicineRejectRequest,
    MedicineResponse,
)
from app.services import medicines as medicines_service
from app.services import reconcile
from app.services.audit import AuditAction, record

router = APIRouter(prefix="/medicines", tags=["medicines"])

MEDICINE_NOT_FOUND = "medicine not found"


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


# Declared first so "pending-review" is not parsed as a medicine id.
@router.get(
    "/pending-review",
    response_model=list[MedicineResponse],
    summary="Medicines awaiting the user's confirmation",
    responses={401: {"description": "Not authenticated."}},
)
async def pending_review(
    user: CurrentUser, session: DbSession
) -> list[MedicineResponse]:
    """The review queue: every unconfirmed, unrejected extraction proposal.

    Oldest first, so the review UI reads as a to-do list. Rejected lines are
    absent by construction -- they were answered, and showing them again would
    make a cleared queue look permanently unfinished.
    """
    rows = await medicines_service.list_pending_review(session, user_id=user.id)
    return [MedicineResponse.model_validate(row) for row in rows]


@router.get(
    "/duplicates",
    response_model=list[DuplicateFlagResponse],
    summary="List suspected duplicate medicines",
    responses={401: {"description": "Not authenticated."}},
)
async def list_duplicates(
    user: CurrentUser,
    session: DbSession,
    include_resolved: bool = Query(
        default=False, description="Include flags the user has already answered."
    ),
) -> list[DuplicateFlagResponse]:
    """Return duplicate pairs the user has not yet resolved.

    Scoped to the caller by joining through ``medicine_a``: the flag table has no
    owner column, so ownership is established by the medicines it points at.
    """
    flags = await reconcile.list_duplicates(
        session, user_id=user.id, include_resolved=include_resolved
    )
    return [DuplicateFlagResponse.model_validate(flag) for flag in flags]


@router.patch(
    "/duplicates/{flag_id}/resolve",
    response_model=DuplicateResolveResponse,
    summary="Resolve a suspected duplicate",
    responses={
        200: {
            "description": "Resolved. A 'merged' resolution tombstones the other row."
        },
        401: {"description": "Not authenticated."},
        404: {"description": "No such flag, or it is not the caller's."},
        409: {"description": "Already resolved."},
    },
)
async def resolve_duplicate(
    flag_id: int,
    payload: DuplicateResolveRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> DuplicateResolveResponse:
    """Dismiss a duplicate as ``keep_both``, ``merged``, or ``not_a_duplicate``.

    ``merged`` is the only destructive option: it tombstones the row the user
    did *not* keep. Nothing is merged field-by-field, because which of two
    differing strengths to keep is a clinical decision the user has just made
    explicitly by naming the survivor.
    """
    try:
        flag, removed = await reconcile.resolve_duplicate(
            session,
            user_id=user.id,
            flag_id=flag_id,
            resolution=payload.resolution,
            kept_medicine_id=payload.kept_medicine_id,
        )
    except reconcile.DuplicateAccessError as exc:
        raise _not_found("duplicate flag not found") from exc
    except reconcile.DuplicateResolutionError as exc:
        # "already resolved" and "invalid payload" are both a 409: the request
        # conflicts with the resource's current state either way.
        raise _conflict(str(exc)) from exc

    await record(
        session,
        action=AuditAction.DUPLICATE_RESOLVED,
        resource_type="duplicate_flag",
        resource_id=flag.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return DuplicateResolveResponse(
        id=flag.id,
        resolved=flag.resolved,
        resolved_at=flag.resolved_at,
        resolution=payload.resolution,
        kept_medicine_id=payload.kept_medicine_id,
        removed_medicine_id=removed,
    )


@router.get(
    "",
    response_model=list[MedicineResponse],
    summary="List the caller's medicines",
    responses={401: {"description": "Not authenticated."}},
)
async def list_medicines(
    user: CurrentUser,
    session: DbSession,
    status_filter: MedicineStatus | None = Query(
        default=None,
        alias="status",
        description="Restrict to one lifecycle state.",
    ),
    confirmed: bool | None = Query(
        default=None,
        description=(
            "true for the user's real medication list, false for the review "
            "queue. Omit to get both."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[MedicineResponse]:
    """Return the caller's medicines, newest first.

    Every row carries ``source``, ``normalized_ingredient``, ``confidence_score``
    and ``status`` so the client can render provenance and trust level without a
    second request: a confirmed row with a ``normalized_ingredient`` is safe to
    use in a safety check, and one without is not.

    For a safety check specifically, pass ``confirmed=true&status=active`` -- an
    unconfirmed OCR line is a proposal, not a drug the user takes.
    """
    rows, _total = await medicines_service.list_medicines(
        session,
        user_id=user.id,
        status=status_filter,
        confirmed=confirmed,
        limit=limit,
        offset=offset,
    )
    return [MedicineResponse.model_validate(row) for row in rows]


@router.post(
    "",
    response_model=MedicineResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a medicine by hand",
    responses={
        201: {"description": "Created, confirmed, normalised, and duplicate-checked."},
        401: {"description": "Not authenticated."},
        422: {"description": "Validation failed, including a rejected status."},
    },
)
async def add_manual_medicine(
    payload: ManualMedicineRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> MedicineResponse:
    """Create a hand-typed medicine, already confirmed.

    Normalised through the same table as OCR output, so a manually typed "Dolo
    650" lands on the same ingredient as an uploaded "Crocin 500mg" and the
    duplicate detector can see them as the same drug.
    """
    medicine, _flags = await medicines_service.add_manual_medicine(
        session, user_id=user.id, payload=payload
    )
    await record(
        session,
        action=AuditAction.MEDICINE_ADDED_MANUALLY,
        resource_type="medicine",
        resource_id=medicine.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return MedicineResponse.model_validate(medicine)


@router.patch(
    "/{medicine_id}/confirm",
    response_model=MedicineResponse,
    summary="Correct and confirm an extracted medicine",
    responses={
        200: {"description": "Confirmed and normalised."},
        401: {"description": "Not authenticated."},
        404: {"description": "No such medicine, or it is not the caller's."},
        409: {"description": "The line was already rejected."},
        422: {"description": "No corrections supplied."},
    },
)
async def confirm_medicine(
    medicine_id: int,
    payload: MedicineConfirmRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> MedicineResponse:
    """Apply the user's corrections, confirm the row, and check for duplicates.

    Edit and confirm in one call because the review UI is a form: the user
    corrects what OCR got wrong and presses Confirm once, and splitting that into
    PATCH-then-PATCH would let a half-edited row sit in the list.

    Only the supplied fields change. ``normalized_ingredient`` is recomputed from
    the corrected values, and the extractor's ``confidence_score`` is cleared --
    it described the machine's uncertainty, which is no longer the operative fact.
    """
    try:
        medicine, _flags = await medicines_service.confirm_medicine(
            session, user_id=user.id, medicine_id=medicine_id, edits=payload
        )
    except medicines_service.MedicineAccessError as exc:
        raise _not_found(MEDICINE_NOT_FOUND) from exc
    except medicines_service.MedicineStateError as exc:
        raise _conflict(str(exc)) from exc

    await record(
        session,
        action=AuditAction.MEDICINE_CONFIRMED,
        resource_type="medicine",
        resource_id=medicine.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return MedicineResponse.model_validate(medicine)


@router.patch(
    "/{medicine_id}/reject",
    response_model=MedicineResponse,
    summary="Dismiss an extracted medicine",
    responses={
        200: {"description": "Marked rejected; excluded from the confirmed list."},
        401: {"description": "Not authenticated."},
        404: {"description": "No such medicine, or it is not the caller's."},
    },
)
async def reject_medicine(
    medicine_id: int,
    payload: MedicineRejectRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> MedicineResponse:
    """Mark an extracted line as not one of the user's medicines.

    The row is kept, not deleted, so the fact that the proposal was seen and
    dismissed survives; it is simply hidden from every list. Re-uploading the same
    document will add a fresh proposal, because suppression is per-row and this
    API has no notion of "this whole prescription was already reviewed".
    """
    try:
        medicine = await medicines_service.reject_medicine(
            session, user_id=user.id, medicine_id=medicine_id, payload=payload
        )
    except medicines_service.MedicineAccessError as exc:
        raise _not_found(MEDICINE_NOT_FOUND) from exc

    await record(
        session,
        action=AuditAction.MEDICINE_REJECTED,
        resource_type="medicine",
        resource_id=medicine.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()
    return MedicineResponse.model_validate(medicine)
