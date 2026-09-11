"""Add optional display_name on asset_identifiers.

Revision ID: 0006_display_name
Revises: 0005_preferred_symbol
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_display_name"
down_revision = "0005_preferred_symbol"
branch_labels = None
depends_on = None

SCHEMA = "portmetrics"


def upgrade() -> None:
    op.add_column(
        "asset_identifiers",
        sa.Column("display_name", sa.Text(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("asset_identifiers", "display_name", schema=SCHEMA)
