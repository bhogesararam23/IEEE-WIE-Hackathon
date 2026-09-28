"""add consent_given_at and soft-delete columns

Revision ID: f1a2b3c4d5e6
Revises: b3f0c825ab04
Create Date: 2026-09-27 12:37:56

Adds the two columns that back the auth and DPDP features:

* ``users.consent_given_at`` -- when the user accepted the consent notice.
* ``deleted_at`` on all eight user-owned tables -- soft-delete tombstones.

Two properties worth keeping if you ever edit this file:

**Entirely additive and NULLable.** Every column defaults to NULL, which is the
same value a pre-existing row already has, so PostgreSQL applies this as a
catalog-only change: no table rewrite, no row locks, no downtime, and no
backfill. In Postgres 11+ ``ADD COLUMN`` with a NULL default does not even
rewrite the table's rows.

**One index per table, not one big index.** Each table gets an index on its own
``deleted_at`` because the filter in ``app.core.soft_delete`` is appended
automatically to *every* SELECT on that table. Without these, listing live rows
would degrade to a sequential scan as soon as tombstones outnumber live rows.
No partial index (``WHERE deleted_at IS NULL``) is used: the global filter
matches NULL-IS-NULL, and a partial index would need to be added to the criteria
expression to be used at all.

``users.consent_given_at`` is intentionally not backfilled. Consent predates
this column only for accounts that never had to be migrated, and inferring
"consented at account creation" would be a false legal record.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "b3f0c825ab04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# audit_logs is absent by design: audit entries outlive the account they
# describe, so they are never tombstoned.
SOFT_DELETE_TABLES = (
    "users",
    "user_profiles",
    "prescriptions",
    "medicines",
    "duplicate_flags",
    "interaction_alerts",
    "evidence_references",
    "reminder_schedules",
)


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=True),
    )
    for table in SOFT_DELETE_TABLES:
        op.add_column(
            table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.create_index(
            op.f(f"ix_{table}_deleted_at"), table, ["deleted_at"], unique=False
        )


def downgrade() -> None:
    # Indexes must go before the columns they cover.
    for table in reversed(SOFT_DELETE_TABLES):
        op.drop_index(op.f(f"ix_{table}_deleted_at"), table_name=table)
        op.drop_column(table, "deleted_at")
    op.drop_column("users", "consent_given_at")
