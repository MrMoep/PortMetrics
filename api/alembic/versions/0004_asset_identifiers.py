"""Add asset_identifiers table (ISIN → WKN from Paperless).

Revision ID: 0004_asset_identifiers
Revises: 0003_nullable_account_id
Create Date: 2026-09-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_asset_identifiers"
down_revision = "0003_nullable_account_id"
branch_labels = None
depends_on = None

SCHEMA = "portmetrics"


def upgrade() -> None:
    op.create_table(
        "asset_identifiers",
        sa.Column("isin", sa.Text(), primary_key=True, nullable=False),
        sa.Column("wkn", sa.Text(), nullable=False),
        sa.Column("paperless_doc_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_asset_identifiers_wkn",
        "asset_identifiers",
        ["wkn"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_asset_identifiers_wkn", table_name="asset_identifiers", schema=SCHEMA)
    op.drop_table("asset_identifiers", schema=SCHEMA)
