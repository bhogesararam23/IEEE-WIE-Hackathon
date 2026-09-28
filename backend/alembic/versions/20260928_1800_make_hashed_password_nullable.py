"""make users.hashed_password nullable for Google-only accounts

Revision ID: 71a945860e98
Revises: 3316d21169ca
Create Date: 2026-09-28 18:00:00.000000

A Google Sign-In account has no password to hash: the identity is Google's
verified ID token, not a secret this app stores. No backfill needed --
relaxing NOT NULL to nullable is safe on a column that already only ever held
non-null values.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "71a945860e98"
down_revision: str | None = "3316d21169ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "users", "hashed_password", existing_type=sa.String(255), nullable=True
    )


def downgrade() -> None:
    # Any null row would violate the tightened constraint; Google-only
    # accounts created since the upgrade have no password to backfill, so
    # this only succeeds if none exist yet.
    op.alter_column(
        "users", "hashed_password", existing_type=sa.String(255), nullable=False
    )
