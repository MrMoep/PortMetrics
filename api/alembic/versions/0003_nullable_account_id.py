"""Allow nullable activities.account_id (Ghostfolio accountId optional).

Revision ID: 0003_nullable_account_id
Revises: 0002_app_settings
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_nullable_account_id"
down_revision = "0002_app_settings"
branch_labels = None
depends_on = None

SCHEMA = "portmetrics"


def upgrade() -> None:
    op.alter_column(
        "activities",
        "account_id",
        existing_type=sa.Text(),
        nullable=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.activities SET account_id = '' WHERE account_id IS NULL"
        )
    )
    op.alter_column(
        "activities",
        "account_id",
        existing_type=sa.Text(),
        nullable=False,
        schema=SCHEMA,
    )
