"""DDI interaction-checking service.

This module sits behind an interface boundary: the router only calls
``check_interactions`` and introspects the returned rows. The data source
(mock CSV today, licensed API tomorrow) can be swapped by replacing
``_load_interactions`` without touching the caller.

Detection rule
--------------
Two confirmed, active medicines whose ``normalized_ingredient`` values appear
together in the seed table — regardless of order — constitute a flagged
interaction. An ingredient-pair that is already open (not soft-deleted) for
this user is *not* re-created, so running the check twice is idempotent.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import InteractionSeverity, MedicineStatus
from app.models.interaction import EvidenceReference, InteractionAlert, interaction_alert_medicines
from app.models.medicine import Medicine

logger = logging.getLogger(__name__)

__all__ = [
    "AlertAccessError",
    "add_evidence",
    "check_interactions",
    "list_alerts",
    "mark_reviewed",
]

_CSV_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "mock_interactions.csv"
)


class AlertAccessError(LookupError):
    """The alert does not exist, or is not the caller's."""


@dataclass(frozen=True, slots=True)
class _InteractionRule:
    """One row from the seed CSV, canonicalised for O(1) lookup."""

    key: frozenset[str]          # frozenset of two lowercased ingredients
    severity: InteractionSeverity
    rationale: str


@lru_cache(maxsize=1)
def _load_interactions() -> tuple[_InteractionRule, ...]:
    """Load the mock DDI dataset once per process."""
    if not _CSV_PATH.is_file():
        logger.error("mock_interactions.csv not found at %s", _CSV_PATH)
        return ()

    rules: list[_InteractionRule] = []
    with _CSV_PATH.open(newline="", encoding="utf-8") as fh:
        for lineno, row in enumerate(csv.DictReader(fh), start=2):
            a = (row.get("ingredient_a") or "").strip()
            b = (row.get("ingredient_b") or "").strip()
            sev_raw = (row.get("severity") or "").strip().lower()
            rationale = (row.get("rationale") or "").strip()
            if not (a and b and sev_raw and rationale):
                logger.warning("Skipping malformed row at line %d", lineno)
                continue
            try:
                severity = InteractionSeverity(sev_raw)
            except ValueError:
                logger.warning("Unknown severity %r at line %d; skipping", sev_raw, lineno)
                continue
            rules.append(
                _InteractionRule(
                    key=frozenset([a.lower(), b.lower()]),
                    severity=severity,
                    rationale=rationale,
                )
            )
    logger.info("Loaded %d interaction rules from %s", len(rules), _CSV_PATH.name)
    return tuple(rules)


# Severity ordering for sort (lower index = higher priority)
_SEVERITY_ORDER = {
    InteractionSeverity.HIGH: 0,
    InteractionSeverity.MODERATE: 1,
    InteractionSeverity.LOW: 2,
    InteractionSeverity.NONE: 3,
}


async def check_interactions(
    session: AsyncSession, *, user_id: int
) -> tuple[list[InteractionAlert], int]:
    """Scan active confirmed medicines and create alerts for new DDI pairs.

    Returns ``(new_alerts, total_active_alert_count)``.

    Idempotent: pairs that already have an open alert are skipped.
    """
    rules = _load_interactions()
    if not rules:
        total = await _count_user_alerts(session, user_id)
        return [], total

    # Collect all confirmed active medicines with a normalised ingredient
    medicines = list(
        (
            await session.scalars(
                select(Medicine).where(
                    Medicine.user_id == user_id,
                    Medicine.is_confirmed.is_(True),
                    Medicine.status == MedicineStatus.ACTIVE,
                    Medicine.normalized_ingredient.is_not(None),
                )
            )
        ).all()
    )

    if len(medicines) < 2:
        total = await _count_user_alerts(session, user_id)
        return [], total

    # Build lookup: ingredient_lower -> list of Medicine rows
    ingredient_map: dict[str, list[Medicine]] = {}
    for med in medicines:
        key = (med.normalized_ingredient or "").strip().lower()
        ingredient_map.setdefault(key, []).append(med)

    # Find existing open alert medicine-id sets (to avoid duplicates)
    existing_open = await _existing_open_alert_sets(session, user_id)

    new_alerts: list[InteractionAlert] = []
    for rule in rules:
        parts = list(rule.key)  # exactly two elements
        a_key, b_key = parts[0], parts[1]
        meds_a = ingredient_map.get(a_key, [])
        meds_b = ingredient_map.get(b_key, [])
        if not (meds_a and meds_b):
            continue

        for med_a in meds_a:
            for med_b in meds_b:
                pair = frozenset([med_a.id, med_b.id])
                if pair in existing_open:
                    logger.debug("Alert for pair %s already open; skipping", pair)
                    continue

                alert = InteractionAlert(
                    user_id=user_id,
                    severity=rule.severity,
                    rationale=rule.rationale,
                    reviewed_by_professional=False,
                )
                alert.medicines = [med_a, med_b]
                session.add(alert)
                existing_open.add(pair)
                new_alerts.append(alert)

    if new_alerts:
        await session.flush()
        logger.info("Created %d new interaction alert(s) for user %s", len(new_alerts), user_id)

    total = await _count_user_alerts(session, user_id)
    return new_alerts, total


async def _existing_open_alert_sets(
    session: AsyncSession, user_id: int
) -> set[frozenset[int]]:
    """Return frozensets of medicine-id pairs that already have an open alert."""
    stmt = (
        select(InteractionAlert)
        .where(InteractionAlert.user_id == user_id)
        .options(selectinload(InteractionAlert.medicines))
    )
    alerts = list((await session.scalars(stmt)).all())
    return {frozenset(m.id for m in a.medicines) for a in alerts if len(a.medicines) >= 2}


async def _count_user_alerts(session: AsyncSession, user_id: int) -> int:
    from sqlalchemy import func
    return int(
        await session.scalar(
            select(func.count())
            .select_from(InteractionAlert)
            .where(InteractionAlert.user_id == user_id)
        )
        or 0
    )


async def list_alerts(
    session: AsyncSession, *, user_id: int
) -> list[InteractionAlert]:
    """Return alerts ordered high→moderate→low, then newest first."""
    alerts = list(
        (
            await session.scalars(
                select(InteractionAlert)
                .where(InteractionAlert.user_id == user_id)
                .options(
                    selectinload(InteractionAlert.medicines),
                    selectinload(InteractionAlert.evidence_references),
                )
            )
        ).all()
    )
    alerts.sort(
        key=lambda a: (
            _SEVERITY_ORDER.get(a.severity, 99),
            -(a.created_at.timestamp() if a.created_at else 0),
        )
    )
    return alerts


async def mark_reviewed(
    session: AsyncSession, *, user_id: int, alert_id: int
) -> InteractionAlert:
    """Set reviewed_by_professional = True on an alert the user owns."""
    alert = await _get_alert(session, user_id=user_id, alert_id=alert_id)
    alert.reviewed_by_professional = True
    await session.flush()
    return alert


async def add_evidence(
    session: AsyncSession,
    *,
    user_id: int,
    alert_id: int,
    source_reference: str | None,
    evidence_items: list[dict],
) -> InteractionAlert:
    """Write source_reference text and/or structured citations to an alert."""
    alert = await _get_alert(session, user_id=user_id, alert_id=alert_id)

    if source_reference is not None:
        alert.source_reference = source_reference

    now = datetime.now(UTC)
    for item in evidence_items:
        ref = EvidenceReference(
            alert_id=alert.id,
            title=item["title"],
            url=item["url"],
            retrieved_at=now,
        )
        session.add(ref)

    await session.flush()
    # Reload evidence_references relationship
    await session.refresh(alert)
    return alert


async def _get_alert(
    session: AsyncSession, *, user_id: int, alert_id: int
) -> InteractionAlert:
    alert = await session.scalar(
        select(InteractionAlert)
        .where(InteractionAlert.id == alert_id, InteractionAlert.user_id == user_id)
        .options(
            selectinload(InteractionAlert.medicines),
            selectinload(InteractionAlert.evidence_references),
        )
    )
    if alert is None:
        raise AlertAccessError(f"alert {alert_id} not found")
    return alert
