"""In-process APScheduler jobs for sync / FIFO / metrics rebuilds."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from portmetrics.config import settings
from portmetrics.db.session import get_engine, session_scope
from portmetrics.fifo.engine import FifoError
from portmetrics.fifo.service import rebuild_lots
from portmetrics.ghostfolio.client import GhostfolioClient, GhostfolioError
from portmetrics.metrics.periods import rebuild_metrics_daily
from portmetrics.sync.activities import sync_ghostfolio_activities

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def job_sync_and_rebuild() -> None:
    if not settings.ghostfolio_url or not settings.ghostfolio_access_token:
        logger.info("Skipping scheduled sync: Ghostfolio not configured")
        return
    engine = get_engine()
    client = GhostfolioClient(settings.ghostfolio_url, settings.ghostfolio_access_token)
    try:
        with session_scope(engine) as session:
            result = sync_ghostfolio_activities(session, client)
            fifo = rebuild_lots(session)
            days = rebuild_metrics_daily(session)
        logger.info(
            "scheduled sync ok: fetched=%s upserted=%s lots=%s metrics_days=%s",
            result.fetched,
            result.upserted,
            fifo.lots_created,
            days,
        )
    except (GhostfolioError, FifoError) as exc:
        logger.exception("scheduled sync failed: %s", exc)
    except Exception:
        logger.exception("scheduled sync failed unexpectedly")


def job_rebuild_metrics() -> None:
    engine = get_engine()
    try:
        with session_scope(engine) as session:
            days = rebuild_metrics_daily(session)
        logger.info("scheduled metrics rebuild ok: days=%s", days)
    except Exception:
        logger.exception("scheduled metrics rebuild failed")


def job_sync_paperless() -> None:
    if not settings.paperless_url or not settings.paperless_token:
        logger.info("Skipping scheduled Paperless sync: not configured")
        return
    from portmetrics.paperless.client import PaperlessClient, PaperlessError
    from portmetrics.paperless.staging import sync_paperless_documents

    engine = get_engine()
    client = PaperlessClient(settings.paperless_url, settings.paperless_token)
    try:
        with session_scope(engine) as session:
            result = sync_paperless_documents(session, client)
        logger.info(
            "scheduled paperless sync ok: scanned=%s upserted=%s skipped=%s",
            result.scanned,
            result.upserted,
            result.skipped,
        )
    except PaperlessError as exc:
        logger.exception("scheduled paperless sync failed: %s", exc)
    except Exception:
        logger.exception("scheduled paperless sync failed unexpectedly")


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        job_sync_and_rebuild,
        trigger=IntervalTrigger(minutes=max(1, settings.sync_interval_minutes)),
        id="sync_ghostfolio",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_rebuild_metrics,
        trigger=IntervalTrigger(minutes=max(1, settings.metrics_interval_minutes)),
        id="rebuild_metrics",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if settings.paperless_sync_interval_minutes > 0:
        scheduler.add_job(
            job_sync_paperless,
            trigger=IntervalTrigger(
                minutes=max(1, settings.paperless_sync_interval_minutes)
            ),
            id="sync_paperless",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    return scheduler


def start_scheduler() -> BackgroundScheduler | None:
    global _scheduler
    if settings.app_env == "test" or not settings.scheduler_enabled:
        logger.info(
            "Background scheduler disabled (env=%s, enabled=%s)",
            settings.app_env,
            settings.scheduler_enabled,
        )
        return None
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    _scheduler = build_scheduler()
    _scheduler.start()
    logger.info(
        "Background scheduler started (sync=%sm, metrics=%sm, paperless=%sm)",
        settings.sync_interval_minutes,
        settings.metrics_interval_minutes,
        settings.paperless_sync_interval_minutes,
    )
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Background scheduler stopped")
