from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

SCHEMA = "portmetrics"


class Base(DeclarativeBase):
    pass


class ActivityType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    FEE = "FEE"
    INTEREST = "INTEREST"


class LotStatus(StrEnum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint(
            "type IN ('BUY','SELL','DIVIDEND','FEE','INTEREST')",
            name="ck_activities_type",
        ),
        Index("ix_activities_isin_trade_date", "isin", "trade_date"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    gf_activity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True, nullable=False)
    account_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    isin: Mapped[str | None] = mapped_column(Text)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    lots: Mapped[list["Lot"]] = relationship(back_populates="activity")


class Lot(Base):
    __tablename__ = "lots"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','PARTIAL','CLOSED')",
            name="ck_lots_status",
        ),
        Index("ix_lots_isin_open_date", "isin", "open_date"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    activity_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.activities.id"),
        nullable=False,
    )
    isin: Mapped[str] = mapped_column(Text, nullable=False)
    open_qty: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    original_qty: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    open_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=LotStatus.OPEN)
    closed_at: Mapped[date | None] = mapped_column(Date)

    activity: Mapped[Activity] = relationship(back_populates="lots")
    consumptions: Mapped[list["LotConsumption"]] = relationship(back_populates="lot")


class LotConsumption(Base):
    __tablename__ = "lot_consumptions"
    __table_args__ = (
        UniqueConstraint("sell_activity_id", "lot_id", name="uq_lot_consumptions_sell_lot"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sell_activity_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.activities.id"),
        nullable=False,
    )
    lot_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.lots.id"),
        nullable=False,
    )
    qty_consumed: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    proceeds: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    realized_gain: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)

    lot: Mapped[Lot] = relationship(back_populates="consumptions")


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__ = (
        UniqueConstraint("isin", "price_date", name="uq_price_snapshots_isin_date"),
        Index("ix_price_snapshots_price_date", "price_date"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    isin: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str | None] = mapped_column(Text)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="ghostfolio")


class MetricsDaily(Base):
    __tablename__ = "metrics_daily"
    __table_args__ = (
        UniqueConstraint("metric_date", name="uq_metrics_daily_date"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    nav: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    invested: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    unrealized_gain: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    mtd_return: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    ytd_return: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    return_30d: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))


class DocumentLink(Base):
    __tablename__ = "document_links"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paperless_doc_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activity_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.activities.id"),
    )
    lot_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{SCHEMA}.lots.id"),
    )
    link_type: Mapped[str] = mapped_column(Text, nullable=False, default="source")


class StagingImport(Base):
    __tablename__ = "staging_imports"
    __table_args__ = (
        UniqueConstraint("paperless_doc_id", name="uq_staging_imports_paperless_doc"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paperless_doc_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    gf_activity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SyncState(Base):
    __tablename__ = "sync_state"
    __table_args__ = (
        UniqueConstraint("source", name="uq_sync_state_source"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSONB)


class AppSetting(Base):
    """Key/value UI settings (JSON). Secrets stay in env."""

    __tablename__ = "app_settings"
    __table_args__ = {"schema": SCHEMA}

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
