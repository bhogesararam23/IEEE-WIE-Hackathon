"""Soft-delete enforcement: one global filter, plus the cascade helper.

The requirement "soft-delete the user and all their data, and exclude it from
all future queries" has two halves that are easy to get wrong:

1. **Marking** the rows as deleted (``soft_delete_user``).
2. **Never showing them again** afterwards. This half is the one that rots.
   If exclusion depended on remembering ``where(User.deleted_at.is_(None))`` in
   every query, the guarantee dies the first time someone writes a new one.

So exclusion is installed *globally* here, as a ``do_orm_execute`` listener on
``Session``. SQLAlchemy routes every ORM SELECT through it, so
``with_loader_criteria`` lands on the statement no matter who wrote it, and it
covers eager loads, lazy loads and ``session.scalar(select(...))`` alike. A
developer cannot forget it because there is nothing to forget.

``AuditLog`` is deliberately absent from ``SOFT_DELETE_MODELS``: an audit trail
that vanishes with the account it describes is not an audit trail. Logs keep
pointing at the tombstoned user row.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, with_loader_criteria

from app.models.audit import AuditLog
from app.models.interaction import EvidenceReference, InteractionAlert
from app.models.medicine import DuplicateFlag, Medicine
from app.models.prescription import Prescription
from app.models.reminder import ReminderSchedule
from app.models.user import User, UserProfile

__all__ = [
    "SOFT_DELETE_MODELS",
    "include_deleted",
    "install_soft_delete_filter",
    "soft_delete_prescription",
    "soft_delete_user",
]


# Every model that participates in soft deletion. Listed explicitly rather than
# discovered by introspection so that adding a model is a deliberate act: a new
# table holding personal data should not silently become un-deletable.
SOFT_DELETE_MODELS: tuple[type, ...] = (
    User,
    UserProfile,
    Prescription,
    Medicine,
    DuplicateFlag,
    InteractionAlert,
    EvidenceReference,
    ReminderSchedule,
)

# Escape hatch. The filter is global, which is what we want for the app, but a
# few legitimate callers need to see tombstones: the deletion endpoint verifying
# its own work, an admin/support view, or a retention job. A ContextVar (rather
# than a session flag) so it cannot leak between concurrent requests.
_include_deleted: ContextVar[bool] = ContextVar("include_deleted", default=False)


@contextmanager
def include_deleted() -> Iterator[None]:
    """Temporarily disable soft-delete filtering inside this task.

    Only for privileged/maintenance reads. Normal request handling must never
    need it.
    """
    token = _include_deleted.set(True)
    try:
        yield
    finally:
        _include_deleted.reset(token)


@event.listens_for(Session, "do_orm_execute")
def _exclude_soft_deleted(state) -> None:  # noqa: ANN001 - ORM event signature
    """Add ``deleted_at IS NULL`` to every ORM SELECT. Installed at import."""
    # Only SELECTs. Bulk UPDATE/DELETE statements must be able to touch tombstoned
    # rows -- that is precisely how a retention purge or a data fix works.
    if not state.is_select or _include_deleted.get():
        return
    for model in SOFT_DELETE_MODELS:
        state.statement = state.statement.options(
            with_loader_criteria(
                model,
                model.deleted_at.is_(None),
                # Also covers aliased entities (self-joins, subquery aliases).
                include_aliases=True,
            )
        )


def install_soft_delete_filter() -> None:
    """No-op kept for explicitness at app startup.

    The listener is registered by the module-level decorator above as soon as
    this module is imported; calling this documents the intent at the call site
    in ``main.py`` and gives us a place to hook future work.
    """


async def soft_delete_user(
    session: AsyncSession, *, user: User, deleted_at: datetime
) -> None:
    """Stamp ``deleted_at`` on the user and every row that belongs to them.

    Deliberately issued as explicit bulk ``UPDATE`` statements instead of
    walking the relationship graph. Reasons:

    * Walking relationships means lazy loads, which in async context need
      ``selectinload`` configured on every parent relationship -- easy to get
      wrong and it fails at runtime, not import time.
    * The SQLAlchemy ``cascade="all, delete-orphan"`` on the ORM relationships
      is paired with ``passive_deletes=True``, so ``session.delete(user)`` would
      hand the whole graph to PostgreSQL and issue **hard** ``DELETE``s. That is
      exactly what this endpoint must not do.
    * Bulk updates are a fixed number of round-trips regardless of how much
      data the user accumulated.

    Child rows are stamped children-first, and ids are collected *before* each
    parent is stamped -- once ``medicines`` is tombstoned, the global filter
    makes its rows unselectable and the flags that reference them could no
    longer be found. Audit logs are intentionally left intact.
    """
    user_id = user.id
    if user_id is None:  # pragma: no cover - guarded by the caller
        raise ValueError("cannot soft-delete an unsaved user")

    # --- medicines, then the duplicate flags that point at them -------------
    medicine_ids = list(
        (await session.execute(select(Medicine.id).where(Medicine.user_id == user_id)))
        .scalars()
        .all()
    )
    if medicine_ids:
        await session.execute(
            update(DuplicateFlag)
            .where(
                (DuplicateFlag.medicine_id_a.in_(medicine_ids))
                | (DuplicateFlag.medicine_id_b.in_(medicine_ids))
            )
            .values(deleted_at=deleted_at)
        )
    await session.execute(
        update(Medicine)
        .where(Medicine.user_id == user_id)
        .values(deleted_at=deleted_at)
    )

    # --- interaction alerts, then their evidence citations -----------------
    alert_ids = list(
        (
            await session.execute(
                select(InteractionAlert.id).where(InteractionAlert.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    if alert_ids:
        await session.execute(
            update(EvidenceReference)
            .where(EvidenceReference.alert_id.in_(alert_ids))
            .values(deleted_at=deleted_at)
        )
    await session.execute(
        update(InteractionAlert)
        .where(InteractionAlert.user_id == user_id)
        .values(deleted_at=deleted_at)
    )

    # --- the remaining user-owned rows -------------------------------------
    for model in (ReminderSchedule, Prescription, UserProfile):
        await session.execute(
            update(model).where(model.user_id == user_id).values(deleted_at=deleted_at)
        )

    # --- finally the user themselves ---------------------------------------
    user.deleted_at = deleted_at
    await session.flush()


async def soft_delete_prescription(
    session: AsyncSession, *, prescription: Prescription, deleted_at: datetime
) -> int:
    """Tombstone one prescription, its medicines, and the flags touching them.

    Used by ``DELETE /prescriptions/{id}``. Same children-first ordering as
    :func:`soft_delete_user` for the same reason: once the medicines are
    tombstoned the global filter makes them unselectable, so the duplicate flags
    that reference them have to be found first.

    Returns the number of medicines tombstoned, so the caller can report it.
    Duplicate flags are tombstoned rather than deleted: a half-deleted flag pair
    would be visible in ``GET /medicines/duplicates`` as a dangling reference.
    """
    medicine_ids = list(
        (
            await session.execute(
                select(Medicine.id).where(Medicine.prescription_id == prescription.id)
            )
        )
        .scalars()
        .all()
    )
    if medicine_ids:
        await session.execute(
            update(DuplicateFlag)
            .where(
                (DuplicateFlag.medicine_id_a.in_(medicine_ids))
                | (DuplicateFlag.medicine_id_b.in_(medicine_ids))
            )
            .values(deleted_at=deleted_at)
        )
        await session.execute(
            update(Medicine)
            .where(Medicine.id.in_(medicine_ids))
            .values(deleted_at=deleted_at)
        )
    prescription.deleted_at = deleted_at
    await session.flush()
    return len(medicine_ids)


async def count_user_tombstones(
    session: AsyncSession, *, user_id: int
) -> dict[str, int]:
    """Count still-visible rows owned by ``user_id``.

    Used by the deletion endpoint's tests and, later, an admin support view. Bypasses
    the soft-delete filter on purpose -- this is the "did the cascade reach
    everything?" assertion, and a filtered count would always answer zero.
    """
    counts: dict[str, int] = {}
    with include_deleted():
        for model in (*SOFT_DELETE_MODELS, AuditLog):
            stmt = select(model).where(model.user_id == user_id)
            result = await session.execute(stmt)
            counts[model.__name__] = len(result.scalars().all())
    return counts
