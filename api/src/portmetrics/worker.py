"""CLI entrypoints for PortMetrics worker jobs."""

from __future__ import annotations

import argparse
import sys

from portmetrics.config import settings
from portmetrics.db.session import get_engine, session_scope
from portmetrics.ghostfolio.client import GhostfolioClient, GhostfolioError
from portmetrics.sync.activities import sync_ghostfolio_activities


def cmd_sync_ghostfolio() -> int:
    if not settings.ghostfolio_url or not settings.ghostfolio_access_token:
        print("GHOSTFOLIO_URL and GHOSTFOLIO_ACCESS_TOKEN are required", file=sys.stderr)
        return 2
    engine = get_engine()
    client = GhostfolioClient(settings.ghostfolio_url, settings.ghostfolio_access_token)
    try:
        with session_scope(engine) as session:
            result = sync_ghostfolio_activities(session, client)
    except GhostfolioError as exc:
        print(f"sync failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"synced ghostfolio activities: fetched={result.fetched} "
        f"upserted={result.upserted} checksum={result.checksum}"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="portmetrics-worker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sync-ghostfolio", help="Pull Ghostfolio activities into PostgreSQL")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.command == "sync-ghostfolio":
        raise SystemExit(cmd_sync_ghostfolio())
    raise SystemExit(2)


if __name__ == "__main__":
    main()
