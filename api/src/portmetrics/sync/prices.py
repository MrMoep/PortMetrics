"""Mirror Ghostfolio daily market prices into price_snapshots."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from portmetrics.assets.identifiers import preferred_symbol_map
from portmetrics.db.models import PriceSnapshot, SyncState
from portmetrics.ghostfolio.client import GhostfolioActivity, GhostfolioClient, GhostfolioError

logger = logging.getLogger(__name__)

GHOSTFOLIO_PRICES_SOURCE = "ghostfolio_prices"
DEFAULT_HISTORY_DAYS = 2000


@dataclass(frozen=True)
class AssetRef:
    data_source: str
    symbol: str
    asset_key: str  # ISIN when present, else symbol (matches FIFO/NAV keys)
    currency: str


@dataclass(frozen=True)
class PriceSyncResult:
    assets: int
    upserted: int
    skipped: int


def asset_key_for_ref(*, isin: str | None, symbol: str) -> str:
    return (isin or symbol).strip()


def discover_assets(
    activities: list[GhostfolioActivity],
    *,
    default_data_source: str = "YAHOO",
    preferred_by_isin: dict[str, str] | None = None,
) -> list[AssetRef]:
    """Unique Ghostfolio assets from activity SymbolProfiles.

    When ``preferred_by_isin`` is set, quote requests use the mapped symbol for
    that ISIN (stable listing) instead of whichever activity was seen last.
    """
    preferred = preferred_by_isin or {}
    found: dict[tuple[str, str], AssetRef] = {}
    for activity in activities:
        symbol = (activity.symbol or "").strip()
        if not symbol:
            continue
        data_source = (activity.data_source or default_data_source).strip() or default_data_source
        key = asset_key_for_ref(isin=activity.isin, symbol=symbol)
        if activity.isin and activity.isin in preferred:
            symbol = preferred[activity.isin]
        found[(data_source, key)] = AssetRef(
            data_source=data_source,
            symbol=symbol,
            asset_key=key,
            currency=(activity.currency or "EUR").upper()[:3],
        )
    return sorted(found.values(), key=lambda a: (a.data_source, a.symbol))


def upsert_price_rows(
    session: Session,
    rows: list[dict],
) -> int:
    if not rows:
        return 0
    # Chunk to keep statement size reasonable for long histories.
    total = 0
    chunk_size = 500
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        stmt = insert(PriceSnapshot).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["isin", "price_date"],
            set_={
                "symbol": stmt.excluded.symbol,
                "close_price": stmt.excluded.close_price,
                "currency": stmt.excluded.currency,
                "source": stmt.excluded.source,
            },
        )
        session.execute(stmt)
        total += len(chunk)
    return total


def _rows_for_symbol(
    *,
    asset: AssetRef,
    historical: list[tuple[date, Decimal]],
    market_price: Decimal | None,
    as_of: date,
) -> list[dict]:
    by_day: dict[date, Decimal] = {day: price for day, price in historical}
    if market_price is not None:
        by_day.setdefault(as_of, market_price)
    return [
        {
            "isin": asset.asset_key,
            "symbol": asset.symbol,
            "price_date": day,
            "close_price": price,
            "currency": asset.currency,
            "source": "ghostfolio",
        }
        for day, price in sorted(by_day.items())
    ]


def update_price_sync_state(
    session: Session,
    *,
    assets: int,
    upserted: int,
    skipped: int,
) -> SyncState:
    existing = session.scalar(select(SyncState).where(SyncState.source == GHOSTFOLIO_PRICES_SOURCE))
    now = datetime.now(UTC)
    meta = {"assets": assets, "upserted": upserted, "skipped": skipped}
    if existing is None:
        existing = SyncState(
            source=GHOSTFOLIO_PRICES_SOURCE,
            last_sync_at=now,
            checksum=None,
            meta=meta,
        )
        session.add(existing)
    else:
        existing.last_sync_at = now
        existing.meta = meta
    return existing


def sync_ghostfolio_prices(
    session: Session,
    client: GhostfolioClient,
    *,
    history_days: int = DEFAULT_HISTORY_DAYS,
    default_data_source: str = "YAHOO",
    activities: list[GhostfolioActivity] | None = None,
    as_of: date | None = None,
) -> PriceSyncResult:
    """Pull daily closes from Ghostfolio symbol API into price_snapshots."""
    fetched = activities if activities is not None else client.list_activities()
    assets = discover_assets(
        fetched,
        default_data_source=default_data_source,
        preferred_by_isin=preferred_symbol_map(session),
    )
    day = as_of or datetime.now(UTC).date()
    upserted = 0
    skipped = 0
    for asset in assets:
        try:
            symbol_data = client.get_symbol(
                asset.data_source,
                asset.symbol,
                include_historical_data=max(1, history_days),
            )
        except GhostfolioError as exc:
            logger.warning(
                "price sync skipped %s/%s: %s",
                asset.data_source,
                asset.symbol,
                exc,
            )
            skipped += 1
            continue
        currency = (symbol_data.currency or asset.currency).upper()[:3]
        ref = AssetRef(
            data_source=symbol_data.data_source or asset.data_source,
            symbol=symbol_data.symbol or asset.symbol,
            asset_key=asset.asset_key,
            currency=currency,
        )
        rows = _rows_for_symbol(
            asset=ref,
            historical=symbol_data.historical,
            market_price=symbol_data.market_price,
            as_of=day,
        )
        if not rows:
            skipped += 1
            continue
        upserted += upsert_price_rows(session, rows)
    update_price_sync_state(
        session,
        assets=len(assets),
        upserted=upserted,
        skipped=skipped,
    )
    return PriceSyncResult(assets=len(assets), upserted=upserted, skipped=skipped)


def price_snapshot_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(PriceSnapshot)) or 0)
