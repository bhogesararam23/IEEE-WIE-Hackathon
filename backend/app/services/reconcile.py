"""Duplicate detection and resolution between a user's confirmed medicines.

The rule this module implements: two rows are a duplicate when they are both
confirmed, both still live, owned by the same user, and share a
``normalized_ingredient``. The shared ingredient is the point -- "Crocin" and
"Dolo" are different products and the same drug, and only the normalised
ingredient reveals that.

Why detection runs at *confirmation* time rather than on a schedule: a duplicate
can only exist once both sides are trusted, and the moment a row becomes trusted
is when a new duplicate can appear. Re-running detection for the whole list after
every confirmation would be quadratic and would repeatedly re-flag pairs the user
has already dismissed. Instead each confirmation asks only "what does this newly
trusted ingredient collide with?".

Why detection runs at *confirmation* time rather than on a schedule: a duplicate
can only exist once both sides are trusted, and the moment a row becomes trusted
is when a new duplicate can appear. Re-running detection for the whole list after
every confirmation would be quadratic and would repeatedly re-flag pairs the user
has already dismissed. Instead each confirmation asks only "what does this newly
trusted ingredient collide with?".

A dismissed pair is not forgotten, and that record lives in the database rather
than in a process-local cache. The ``duplicate_flags`` row *is* the memory: the
unique constraint guarantees one row per pair, and ``resolved`` records the
answer. A user who says "no, those really are two different strengths" does not
want to be asked again on the next upload, and reading the flag is both durable
across restarts and impossible to desynchronise from the data it describes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.soft_delete import include_deleted
from app.models.enums import MedicineStatus
from app.models.medicine import DuplicateFlag, Medicine

logger = logging.getLogger(__name__)

__all__ = [
    "DuplicateAccessError",
    "DuplicateResolutionError",
    "flag_duplicates_for",
    "list_duplicates",
    "resolve_duplicate",
]


class DuplicateAccessError(LookupError):
    """The flag does not exist, or is not the caller's."""


class DuplicateResolutionError(ValueError):
    """The requested resolution is not valid for this flag."""


@dataclass(frozen=True, slots=True)
class _Pair:
    """A canonical, order-independent medicine pair.

    The unique constraint on ``(medicine_id_a, medicine_id_b)`` is
    order-sensitive, so without canonical ordering the same duplicate would
    insert successfully twice -- once as (3, 7) and once as (7, 3) -- and the
    user would see two flags for one problem.
    """

    low: int
    high: int

    @classmethod
    def of(cls, first: int, second: int) -> _Pair:
        if first == second:
            raise ValueError("a medicine cannot duplicate itself")
        return cls(*sorted((first, second)))

    def as_columns(self) -> tuple[int, int]:
        return self.low, self.high


def _ingredient_key(ingredient: str) -> str:
    """Case- and whitespace-insensitive key for comparing ingredient strings."""
    return " ".join(ingredient.lower().split())


async def flag_duplicates_for(
    session: AsyncSession, *, medicine: Medicine
) -> list[DuplicateFlag]:
    """Find and persist duplicates for one newly-confirmed medicine.

    Returns the flags created, which may be empty. Only compares against rows
    that are themselves confirmed and not rejected -- an unconfirmed OCR line is
    a *proposal*, and flagging a proposal against a real medicine would produce
    noise the user has to dismiss before they have even seen the list.

    A pair that already has a flag is left alone, whether or not it was
    resolved. That single rule covers both "do not raise the same duplicate
    twice" and "do not re-ask about one the user already answered", and it leans
    on the unique constraint to make the check race-free.

    The existence check looks through tombstones too. A flag hidden by a
    soft-delete is still occupying the pair in the unique index, so ignoring it
    would turn a re-confirmation into a constraint violation rather than a
    no-op.
    """
    ingredient = medicine.normalized_ingredient
    if not ingredient:
        # Not an error: an unmatched drug name is a normal outcome, and the
        # whole reason a manual entry is not always comparable. There is nothing
        # to match on, so nothing is flagged.
        return []

    key = _ingredient_key(ingredient)
    candidates = list(
        (
            await session.scalars(
                select(Medicine).where(
                    Medicine.user_id == medicine.user_id,
                    Medicine.id != medicine.id,
                    Medicine.is_confirmed.is_(True),
                    Medicine.status != MedicineStatus.REJECTED,
                    func.lower(Medicine.normalized_ingredient) == key,
                )
            )
        ).all()
    )
    if not candidates:
        return []

    created: list[DuplicateFlag] = []
    for other in candidates:
        pair = _Pair.of(medicine.id, other.id)
        low, high = pair.as_columns()

        with include_deleted():
            already = await session.scalar(
                select(DuplicateFlag.id).where(
                    DuplicateFlag.medicine_id_a == low,
                    DuplicateFlag.medicine_id_b == high,
                )
            )
        if already is not None:
            logger.debug("Pair %s already has a flag; not re-raising", pair)
            continue

        flag = DuplicateFlag(medicine_id_a=low, medicine_id_b=high)
        session.add(flag)
        created.append(flag)

    if created:
        await session.flush()
        logger.info(
            "Flagged %d duplicate(s) for medicine %s (%s)",
            len(created),
            medicine.id,
            ingredient,
        )
    return created


async def list_duplicates(
    session: AsyncSession, *, user_id: int, include_resolved: bool = False
) -> list[DuplicateFlag]:
    """Return the caller's duplicate flags, newest first, with both medicines loaded.

    Scoped by the medicines' ``user_id`` rather than by anything on the flag
    table itself: the flag has no ``user_id`` column, and a duplicate is defined
    by both of its medicines belonging to the same person, so joining through
    ``medicine_a`` is what ties the flag to an owner. Without it, any user could
    read every other user's suspected duplicates.
    """
    conditions = [Medicine.user_id == user_id]
    if not include_resolved:
        conditions.append(DuplicateFlag.resolved.is_(False))

    stmt = (
        select(DuplicateFlag)
        .join(DuplicateFlag.medicine_a)
        .options(
            selectinload(DuplicateFlag.medicine_a),
            selectinload(DuplicateFlag.medicine_b),
        )
        .where(*conditions)
        .order_by(DuplicateFlag.detected_at.desc(), DuplicateFlag.id.desc())
    )
    return list((await session.scalars(stmt)).all())


async def resolve_duplicate(
    session: AsyncSession,
    *,
    user_id: int,
    flag_id: int,
    resolution: str,
    kept_medicine_id: int | None = None,
    now: datetime | None = None,
) -> tuple[DuplicateFlag, int | None]:
    """Resolve a flag. Returns ``(flag, removed_medicine_id_or_None)``.

    ``merged`` tombstones the non-kept medicine and, importantly, the duplicate
    flags that referenced it -- otherwise resolving one pair would leave a second
    flag pointing at a hidden row. The surviving row keeps its own data; nothing
    is copied between them, because guessing which fields to merge is a clinical
    judgement this API should not make silently.
    """
    flag = await session.scalar(
        select(DuplicateFlag)
        .join(DuplicateFlag.medicine_a)
        .options(
            selectinload(DuplicateFlag.medicine_a),
            selectinload(DuplicateFlag.medicine_b),
        )
        .where(DuplicateFlag.id == flag_id, Medicine.user_id == user_id)
    )
    if flag is None:
        raise DuplicateAccessError(f"duplicate flag {flag_id} not found")
    if flag.resolved:
        raise DuplicateResolutionError("this duplicate has already been resolved")

    resolved_at = now or datetime.now(UTC)
    removed: int | None = None

    if resolution == "merged":
        if kept_medicine_id is None:
            raise DuplicateResolutionError(
                "'merged' requires kept_medicine_id naming the row to keep"
            )
        pair_ids = {flag.medicine_id_a, flag.medicine_id_b}
        if kept_medicine_id not in pair_ids:
            raise DuplicateResolutionError(
                "kept_medicine_id must be one of the two flagged medicines"
            )
        removed = next(i for i in pair_ids if i != kept_medicine_id)
        await _tombstone_medicine(session, removed, resolved_at)

    flag.resolved = True
    flag.resolved_at = resolved_at
    await session.flush()
    return flag, removed


async def _tombstone_medicine(
    session: AsyncSession, medicine_id: int, deleted_at: datetime
) -> None:
    """Hide a merged-away medicine and every flag that pointed at it."""
    await session.execute(
        update(DuplicateFlag)
        .where(
            or_(
                DuplicateFlag.medicine_id_a == medicine_id,
                DuplicateFlag.medicine_id_b == medicine_id,
            ),
            DuplicateFlag.resolved.is_(False),
        )
        .values(deleted_at=deleted_at, resolved=True, resolved_at=deleted_at)
    )
    await session.execute(
        update(Medicine).where(Medicine.id == medicine_id).values(deleted_at=deleted_at)
    )
