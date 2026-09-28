"""Audit-trail writer.

Every state-changing request routes through :func:`record` so the trail cannot
be quietly skipped by a new endpoint. The action vocabulary is a closed
``StrEnum`` on purpose: an ad-hoc string in a new code path is how audit logs
become unqueryable six months later.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

__all__ = ["AuditAction", "record"]


class AuditAction(StrEnum):
    """Canonical action names. Persisted lowercase-dotted, never enum member names."""

    SIGNUP = "auth.signup"
    # Recorded with a NULL user_id, because no user was created.
    SIGNUP_FAILED = "auth.signup_failed"
    LOGIN = "auth.login"
    # Also recorded with a NULL user_id (that column is nullable precisely so a
    # failure against an unknown email still leaves a trace).
    LOGIN_FAILED = "auth.login_failed"
    PROFILE_READ = "user.profile.read"
    PROFILE_CREATED = "user.profile.created"
    PROFILE_UPDATED = "user.profile.updated"
    CONSENT_RECORDED = "user.consent.recorded"
    ACCOUNT_SOFT_DELETED = "user.account.soft_deleted"

    # --- prescriptions ---
    # Distinct from the medicine actions below: one is "a file arrived", the
    # other is "a line of text was accepted or dismissed".
    PRESCRIPTION_UPLOADED = "prescription.uploaded"
    PRESCRIPTION_REJECTED_UPLOAD = "prescription.upload_rejected"
    PRESCRIPTION_READ = "prescription.read"
    PRESCRIPTION_DELETED = "prescription.deleted"

    # --- OCR extraction ---
    OCR_RESULTS_RECORDED = "prescription.ocr_results_recorded"

    # --- medicines ---
    MEDICINE_CONFIRMED = "medicine.confirmed"
    MEDICINE_REJECTED = "medicine.rejected"
    MEDICINE_ADDED_MANUALLY = "medicine.added_manually"
    MEDICINE_DISCONTINUED = "medicine.discontinued"

    # --- reconciliation ---
    DUPLICATE_DETECTED = "medicine.duplicate_detected"
    DUPLICATE_RESOLVED = "medicine.duplicate_resolved"

    # --- interaction alerts ---
    INTERACTION_CHECK_RUN = "interaction.check_run"
    INTERACTION_ALERT_REVIEWED = "interaction.alert_reviewed"
    INTERACTION_EVIDENCE_ADDED = "interaction.evidence_added"

    # --- reminders ---
    REMINDER_CREATED = "reminder.created"
    REMINDER_UPDATED = "reminder.updated"
    REMINDER_DELETED = "reminder.deleted"

    # --- reports ---
    REPORT_GENERATED = "report.generated"

    # --- audit log access ---
    AUDIT_LOG_READ = "audit.read"


async def record(
    session: AsyncSession,
    *,
    action: AuditAction,
    resource_type: str,
    resource_id: int | str | None,
    user_id: int | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Append one audit entry and flush it.

    Flushed, not committed: the caller owns the transaction, so the audit row
    and the thing it describes commit or roll back together. A login that
    succeeded but whose audit insert failed should not leave an unlogged
    success.
    """
    entry = AuditLog(
        action=str(action),
        resource_type=resource_type,
        # Always a string: resource_id is polymorphic, and String(64) will not
        # hold a raw UUID's repr alongside ints without the coercion being
        # explicit somewhere.
        resource_id=str(resource_id) if resource_id is not None else None,
        user_id=user_id,
        # 45 chars is the longest possible IPv6 textual form, e.g.
        # 2001:0db8:85a3:0000:0000:8a2e:0370:7334.
        ip_address=(ip_address or None),
    )
    session.add(entry)
    await session.flush()
    return entry
