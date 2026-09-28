"""initial schema

Revision ID: b3f0c825ab04
Revises:
Create Date: 2026-09-27 12:02:13.969474

Enum types are created and dropped explicitly here. Left to its own devices,
Alembic emits CREATE TYPE implicitly inside CREATE TABLE but never emits the
matching DROP TYPE, so `downgrade` would leave all five types behind and the next
`upgrade` would fail with `DuplicateObjectError: type ... already exists`.
Declaring them with `create_type=False` keeps this file the single owner of the
lifecycle.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b3f0c825ab04"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_context_type = postgresql.ENUM(
    "general",
    "planning_pregnancy",
    "pregnant",
    "breastfeeding",
    name="user_context_type",
    create_type=False,
)
prescription_file_type = postgresql.ENUM(
    "image",
    "pdf",
    name="prescription_file_type",
    create_type=False,
)
medicine_source_type = postgresql.ENUM(
    "prescription",
    "otc",
    "self_reported",
    name="medicine_source_type",
    create_type=False,
)
medicine_status = postgresql.ENUM(
    "active",
    "discontinued",
    name="medicine_status",
    create_type=False,
)
interaction_severity = postgresql.ENUM(
    "high",
    "moderate",
    "low",
    "none",
    name="interaction_severity",
    create_type=False,
)

# Order matters on the way down: drop dependent tables before their types.
ENUM_TYPES = (
    interaction_severity,
    user_context_type,
    prescription_file_type,
    medicine_source_type,
    medicine_status,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"])
    op.create_index(op.f("ix_audit_logs_timestamp"), "audit_logs", ["timestamp"])
    op.create_index(op.f("ix_audit_logs_user_id"), "audit_logs", ["user_id"])

    op.create_table(
        "interaction_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("severity", interaction_severity, nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by_professional",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_interaction_alerts_severity"), "interaction_alerts", ["severity"]
    )
    op.create_index(
        op.f("ix_interaction_alerts_user_id"), "interaction_alerts", ["user_id"]
    )

    op.create_table(
        "prescriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("file_url", sa.String(length=1024), nullable=False),
        sa.Column("file_type", prescription_file_type, nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_type", medicine_source_type, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_prescriptions_user_id"), "prescriptions", ["user_id"])

    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "context_type",
            user_context_type,
            server_default="general",
            nullable=False,
        ),
        sa.Column("trimester", sa.Integer(), nullable=True),
        sa.Column("infant_age_months", sa.Integer(), nullable=True),
        sa.Column("is_premature_infant", sa.Boolean(), nullable=True),
        sa.CheckConstraint(
            "infant_age_months IS NULL OR infant_age_months >= 0",
            name="ck_user_profiles_infant_age",
        ),
        sa.CheckConstraint(
            "trimester IS NULL OR trimester BETWEEN 1 AND 3",
            name="ck_user_profiles_trimester",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_profiles_user_id"), "user_profiles", ["user_id"], unique=True
    )

    op.create_table(
        "evidence_references",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alert_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["interaction_alerts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evidence_references_alert_id"), "evidence_references", ["alert_id"]
    )

    op.create_table(
        "medicines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prescription_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("raw_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_ingredient", sa.String(length=255), nullable=True),
        sa.Column("brand_name", sa.String(length=255), nullable=True),
        sa.Column("strength", sa.String(length=100), nullable=True),
        sa.Column("dose", sa.String(length=100), nullable=True),
        sa.Column("frequency", sa.String(length=100), nullable=True),
        sa.Column("duration", sa.String(length=100), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column(
            "is_confirmed",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("status", medicine_status, server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence_score IS NULL"
            " OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="ck_medicines_confidence_score",
        ),
        sa.ForeignKeyConstraint(
            ["prescription_id"], ["prescriptions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_medicines_prescription_id"), "medicines", ["prescription_id"]
    )
    op.create_index(op.f("ix_medicines_user_id"), "medicines", ["user_id"])
    op.create_index(
        "ix_medicines_user_normalized_ingredient",
        "medicines",
        ["user_id", "normalized_ingredient"],
    )

    op.create_table(
        "duplicate_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("medicine_id_a", sa.Integer(), nullable=False),
        sa.Column("medicine_id_b", sa.Integer(), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint(
            "medicine_id_a <> medicine_id_b", name="ck_duplicate_flags_distinct"
        ),
        sa.ForeignKeyConstraint(
            ["medicine_id_a"], ["medicines.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["medicine_id_b"], ["medicines.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "medicine_id_a", "medicine_id_b", name="uq_duplicate_flags_pair"
        ),
    )
    op.create_index(
        op.f("ix_duplicate_flags_medicine_id_a"), "duplicate_flags", ["medicine_id_a"]
    )
    op.create_index(
        op.f("ix_duplicate_flags_medicine_id_b"), "duplicate_flags", ["medicine_id_b"]
    )

    op.create_table(
        "interaction_alert_medicines",
        sa.Column("alert_id", sa.Integer(), nullable=False),
        sa.Column("medicine_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["interaction_alerts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["medicine_id"], ["medicines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("alert_id", "medicine_id"),
    )
    op.create_index(
        "ix_interaction_alert_medicines_medicine_id",
        "interaction_alert_medicines",
        ["medicine_id"],
    )

    op.create_table(
        "reminder_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("medicine_id", sa.Integer(), nullable=False),
        sa.Column("time_of_day", sa.Time(), nullable=False),
        sa.Column("frequency", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["medicine_id"], ["medicines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_reminder_schedules_medicine_id"), "reminder_schedules", ["medicine_id"]
    )
    op.create_index(
        op.f("ix_reminder_schedules_user_id"), "reminder_schedules", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_reminder_schedules_user_id"), table_name="reminder_schedules"
    )
    op.drop_index(
        op.f("ix_reminder_schedules_medicine_id"), table_name="reminder_schedules"
    )
    op.drop_table("reminder_schedules")

    op.drop_index(
        "ix_interaction_alert_medicines_medicine_id",
        table_name="interaction_alert_medicines",
    )
    op.drop_table("interaction_alert_medicines")

    op.drop_index(
        op.f("ix_duplicate_flags_medicine_id_b"), table_name="duplicate_flags"
    )
    op.drop_index(
        op.f("ix_duplicate_flags_medicine_id_a"), table_name="duplicate_flags"
    )
    op.drop_table("duplicate_flags")

    op.drop_index("ix_medicines_user_normalized_ingredient", table_name="medicines")
    op.drop_index(op.f("ix_medicines_user_id"), table_name="medicines")
    op.drop_index(op.f("ix_medicines_prescription_id"), table_name="medicines")
    op.drop_table("medicines")

    op.drop_index(
        op.f("ix_evidence_references_alert_id"), table_name="evidence_references"
    )
    op.drop_table("evidence_references")

    op.drop_index(op.f("ix_user_profiles_user_id"), table_name="user_profiles")
    op.drop_table("user_profiles")

    op.drop_index(op.f("ix_prescriptions_user_id"), table_name="prescriptions")
    op.drop_table("prescriptions")

    op.drop_index(
        op.f("ix_interaction_alerts_user_id"), table_name="interaction_alerts"
    )
    op.drop_index(
        op.f("ix_interaction_alerts_severity"), table_name="interaction_alerts"
    )
    op.drop_table("interaction_alerts")

    op.drop_index(op.f("ix_audit_logs_user_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_timestamp"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    bind = op.get_bind()
    for enum_type in reversed(ENUM_TYPES):
        enum_type.drop(bind, checkfirst=True)
