"""Full Ghostfolio → PortMetrics mirror (activities, prices, FIFO, metrics)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from portmetrics.config import settings
from portmetrics.fifo.service import RebuildResult, rebuild_lots
from portmetrics.ghostfolio.client import GhostfolioClient
from portmetrics.metrics.periods import rebuild_metrics_daily
from portmetrics.sync.activities import SyncResult, sync_ghostfolio_activities
from portmetrics.sync.prices import PriceSyncResult, sync_ghostfolio_prices


@dataclass(frozen=True)
class MirrorSyncResult:
    activities: SyncResult
    prices: PriceSyncResult
    fifo: RebuildResult
    metrics_days: int


def sync_ghostfolio_mirror(
    session: Session,
    client: GhostfolioClient,
    *,
    include_prices: bool = True,
    history_days: int | None = None,
    default_data_source: str | None = None,
) -> MirrorSyncResult:
    """Pull Ghostfolio state into PostgreSQL and rebuild derived tables."""
    activities = sync_ghostfolio_activities(session, client)
    if include_prices:
        prices = sync_ghostfolio_prices(
            session,
            client,
            history_days=(
                history_days
                if history_days is not None
                else settings.ghostfolio_price_history_days
            ),
            default_data_source=(
                default_data_source
                if default_data_source is not None
                else settings.ghostfolio_data_source
            ),
        )
    else:
        prices = PriceSyncResult(assets=0, upserted=0, skipped=0)
    fifo = rebuild_lots(session)
    metrics_days = rebuild_metrics_daily(session)
    return MirrorSyncResult(
        activities=activities,
        prices=prices,
        fifo=fifo,
        metrics_days=metrics_days,
    )
