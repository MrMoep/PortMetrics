"""Add account_id to lots for depot-scoped FIFO.

Revision ID: 0008_lots_account_id
Revises: 0007_accounts
Create Date: 2026-09-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_lots_account_id"
down_revision = "0007_accounts"
branch_labels = None
depends_on = None

SCHEMA = "portmetrics"


def upgrade() -> None:
    op.add_column(
        "lots",
        sa.Column("account_id", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    # Backfill from buy activity when present.
    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA}.lots AS l
            SET account_id = a.account_id
            FROM {SCHEMA}.activities AS a
            WHERE l.activity_id = a.id
            """
        )
    )
    op.create_index(
        "ix_lots_account_isin_status_open_date",
        "lots",
        ["account_id", "isin", "status", "open_date"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_lots_account_isin_status_open_date",
        table_name="lots",
        schema=SCHEMA,
    )
    op.drop_column("lots", "account_id", schema=SCHEMA)
