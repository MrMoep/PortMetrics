"""Add preferred_symbol; allow nullable WKN on asset_identifiers.

Revision ID: 0005_preferred_symbol
Revises: 0004_asset_identifiers
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_preferred_symbol"
down_revision = "0004_asset_identifiers"
branch_labels = None
depends_on = None

SCHEMA = "portmetrics"


def upgrade() -> None:
    op.add_column(
        "asset_identifiers",
        sa.Column("preferred_symbol", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.alter_column(
        "asset_identifiers",
        "wkn",
        existing_type=sa.Text(),
        nullable=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.asset_identifiers SET wkn = '' WHERE wkn IS NULL"
        )
    )
    op.alter_column(
        "asset_identifiers",
        "wkn",
        existing_type=sa.Text(),
        nullable=False,
        schema=SCHEMA,
    )
    op.drop_column("asset_identifiers", "preferred_symbol", schema=SCHEMA)
