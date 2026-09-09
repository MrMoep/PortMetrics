"""Initial portmetrics schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "portmetrics"


def upgrade() -> None:
    op.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))

    op.create_table(
        "activities",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("gf_activity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("isin", sa.Text(), nullable=True),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 8), nullable=False),
        sa.Column("fee", sa.Numeric(18, 8), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "type IN ('BUY','SELL','DIVIDEND','FEE','INTEREST')",
            name="ck_activities_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gf_activity_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_activities_isin_trade_date",
        "activities",
        ["isin", "trade_date"],
        schema=SCHEMA,
    )

    op.create_table(
        "lots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("open_qty", sa.Numeric(18, 8), nullable=False),
        sa.Column("original_qty", sa.Numeric(18, 8), nullable=False),
        sa.Column("cost_basis", sa.Numeric(18, 8), nullable=False),
        sa.Column("open_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("closed_at", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "status IN ('OPEN','PARTIAL','CLOSED')",
            name="ck_lots_status",
        ),
        sa.ForeignKeyConstraint(["activity_id"], [f"{SCHEMA}.activities.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_lots_isin_open_date",
        "lots",
        ["isin", "open_date"],
        schema=SCHEMA,
    )

    op.create_table(
        "lot_consumptions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("sell_activity_id", sa.BigInteger(), nullable=False),
        sa.Column("lot_id", sa.BigInteger(), nullable=False),
        sa.Column("qty_consumed", sa.Numeric(18, 8), nullable=False),
        sa.Column("proceeds", sa.Numeric(18, 8), nullable=False),
        sa.Column("realized_gain", sa.Numeric(18, 8), nullable=False),
        sa.ForeignKeyConstraint(["lot_id"], [f"{SCHEMA}.lots.id"]),
        sa.ForeignKeyConstraint(["sell_activity_id"], [f"{SCHEMA}.activities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sell_activity_id", "lot_id", name="uq_lot_consumptions_sell_lot"),
        schema=SCHEMA,
    )

    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("isin", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("close_price", sa.Numeric(18, 8), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isin", "price_date", name="uq_price_snapshots_isin_date"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_price_snapshots_price_date",
        "price_snapshots",
        ["price_date"],
        schema=SCHEMA,
    )

    op.create_table(
        "metrics_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(18, 8), nullable=False),
        sa.Column("invested", sa.Numeric(18, 8), nullable=False),
        sa.Column("unrealized_gain", sa.Numeric(18, 8), nullable=True),
        sa.Column("mtd_return", sa.Numeric(18, 8), nullable=True),
        sa.Column("ytd_return", sa.Numeric(18, 8), nullable=True),
        sa.Column("return_30d", sa.Numeric(18, 8), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("metric_date", name="uq_metrics_daily_date"),
        schema=SCHEMA,
    )

    op.create_table(
        "document_links",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("paperless_doc_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_id", sa.BigInteger(), nullable=True),
        sa.Column("lot_id", sa.BigInteger(), nullable=True),
        sa.Column("link_type", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], [f"{SCHEMA}.activities.id"]),
        sa.ForeignKeyConstraint(["lot_id"], [f"{SCHEMA}.lots.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "staging_imports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("paperless_doc_id", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("gf_activity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("paperless_doc_id", name="uq_staging_imports_paperless_doc"),
        schema=SCHEMA,
    )

    op.create_table(
        "sync_state",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("checksum", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", name="uq_sync_state_source"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("sync_state", schema=SCHEMA)
    op.drop_table("staging_imports", schema=SCHEMA)
    op.drop_table("document_links", schema=SCHEMA)
    op.drop_table("metrics_daily", schema=SCHEMA)
    op.drop_index("ix_price_snapshots_price_date", table_name="price_snapshots", schema=SCHEMA)
    op.drop_table("price_snapshots", schema=SCHEMA)
    op.drop_table("lot_consumptions", schema=SCHEMA)
    op.drop_index("ix_lots_isin_open_date", table_name="lots", schema=SCHEMA)
    op.drop_table("lots", schema=SCHEMA)
    op.drop_index("ix_activities_isin_trade_date", table_name="activities", schema=SCHEMA)
    op.drop_table("activities", schema=SCHEMA)
    op.execute(sa.text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
