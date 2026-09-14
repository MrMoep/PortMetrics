"""Add depot_transfers for internal account-to-account moves.

Revision ID: 0009_depot_transfers
Revises: 0008_lots_account_id
Create Date: 2026-09-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_depot_transfers"
down_revision = "0008_lots_account_id"
branch_labels = None
depends_on = None

SCHEMA = "portmetrics"


def upgrade() -> None:
    op.create_table(
        "depot_transfers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("from_account_id", sa.Text(), nullable=False),
        sa.Column("to_account_id", sa.Text(), nullable=False),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("transfer_date", sa.Date(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "from_account_id <> to_account_id",
            name="ck_depot_transfers_distinct_accounts",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_depot_transfers_qty_positive"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_depot_transfers_date",
        "depot_transfers",
        ["transfer_date"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_depot_transfers_date",
        table_name="depot_transfers",
        schema=SCHEMA,
    )
    op.drop_table("depot_transfers", schema=SCHEMA)
