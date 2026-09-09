"""CLI entrypoints for PortMetrics worker jobs."""

from __future__ import annotations

import argparse
import sys

from portmetrics.config import settings
from portmetrics.db.session import get_engine, session_scope
from portmetrics.fifo.engine import FifoError
from portmetrics.fifo.service import rebuild_lots
from portmetrics.ghostfolio.client import GhostfolioClient, GhostfolioError
from portmetrics.sync.activities import sync_ghostfolio_activities
from portmetrics.sync.prices import sync_ghostfolio_prices


def cmd_sync_ghostfolio() -> int:
    if not settings.ghostfolio_url or not settings.ghostfolio_access_token:
        print("GHOSTFOLIO_URL and GHOSTFOLIO_ACCESS_TOKEN are required", file=sys.stderr)
        return 2
    engine = get_engine()
    client = GhostfolioClient(settings.ghostfolio_url, settings.ghostfolio_access_token)
    try:
        with session_scope(engine) as session:
            result = sync_ghostfolio_activities(session, client)
            prices = sync_ghostfolio_prices(
                session,
                client,
                history_days=settings.ghostfolio_price_history_days,
                default_data_source=settings.ghostfolio_data_source,
            )
            fifo = rebuild_lots(session)
    except GhostfolioError as exc:
        print(f"sync failed: {exc}", file=sys.stderr)
        return 1
    except FifoError as exc:
        print(f"fifo rebuild failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"synced ghostfolio activities: fetched={result.fetched} "
        f"upserted={result.upserted} checksum={result.checksum} "
        f"prices={prices.upserted}/{prices.assets} "
        f"lots={fifo.lots_created} consumptions={fifo.consumptions}"
    )
    return 0


def cmd_rebuild_fifo() -> int:
    engine = get_engine()
    try:
        with session_scope(engine) as session:
            result = rebuild_lots(session)
    except FifoError as exc:
        print(f"fifo rebuild failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"fifo rebuild: lots={result.lots_created} "
        f"consumptions={result.consumptions} activities={result.activities_processed}"
    )
    return 0


def cmd_rebuild_metrics() -> int:
    from portmetrics.metrics.periods import rebuild_metrics_daily

    engine = get_engine()
    with session_scope(engine) as session:
        count = rebuild_metrics_daily(session)
    print(f"metrics rebuild: days_written={count}")
    return 0


def cmd_sync_paperless() -> int:
    from portmetrics.paperless.client import PaperlessClient, PaperlessError
    from portmetrics.paperless.staging import sync_paperless_documents

    if not settings.paperless_url or not settings.paperless_token:
        print("PAPERLESS_URL and PAPERLESS_TOKEN are required", file=sys.stderr)
        return 2
    engine = get_engine()
    client = PaperlessClient(settings.paperless_url, settings.paperless_token)
    try:
        with session_scope(engine) as session:
            result = sync_paperless_documents(session, client)
    except PaperlessError as exc:
        print(f"paperless sync failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"synced paperless: scanned={result.scanned} "
        f"upserted={result.upserted} skipped={result.skipped}"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="portmetrics-worker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sync-ghostfolio", help="Pull Ghostfolio activities into PostgreSQL")
    sub.add_parser("rebuild-fifo", help="Rebuild FIFO lots from activities")
    sub.add_parser("rebuild-metrics", help="Rebuild daily portfolio metrics")
    sub.add_parser("sync-paperless", help="Pull Paperless docs into staging_imports")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.command == "sync-ghostfolio":
        raise SystemExit(cmd_sync_ghostfolio())
    if args.command == "rebuild-fifo":
        raise SystemExit(cmd_rebuild_fifo())
    if args.command == "rebuild-metrics":
        raise SystemExit(cmd_rebuild_metrics())
    if args.command == "sync-paperless":
        raise SystemExit(cmd_sync_paperless())
    raise SystemExit(2)


if __name__ == "__main__":
    main()
