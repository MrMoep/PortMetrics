from __future__ import annotations

from pathlib import Path

from portmetrics.logging_setup import configure_logging
from portmetrics.scheduler import (
    build_scheduler,
    job_rebuild_metrics,
    job_sync_and_rebuild,
    start_scheduler,
    stop_scheduler,
)


def test_build_scheduler_registers_jobs() -> None:
    scheduler = build_scheduler()
    ids = {job.id for job in scheduler.get_jobs()}
    assert ids == {"sync_ghostfolio", "rebuild_metrics"}


def test_job_sync_skips_without_config(monkeypatch) -> None:
    monkeypatch.setattr("portmetrics.scheduler.settings.ghostfolio_url", None)
    monkeypatch.setattr("portmetrics.scheduler.settings.ghostfolio_access_token", None)
    # Should return without contacting Ghostfolio / DB.
    job_sync_and_rebuild()


def test_start_scheduler_disabled_in_test_env(monkeypatch) -> None:
    monkeypatch.setattr("portmetrics.scheduler.settings.app_env", "test")
    monkeypatch.setattr("portmetrics.scheduler.settings.scheduler_enabled", True)
    assert start_scheduler() is None


def test_start_scheduler_respects_flag(monkeypatch) -> None:
    monkeypatch.setattr("portmetrics.scheduler.settings.app_env", "production")
    monkeypatch.setattr("portmetrics.scheduler.settings.scheduler_enabled", False)
    assert start_scheduler() is None


def test_start_and_stop_scheduler(monkeypatch) -> None:
    monkeypatch.setattr("portmetrics.scheduler.settings.app_env", "production")
    monkeypatch.setattr("portmetrics.scheduler.settings.scheduler_enabled", True)
    monkeypatch.setattr("portmetrics.scheduler.settings.sync_interval_minutes", 60)
    monkeypatch.setattr("portmetrics.scheduler.settings.metrics_interval_minutes", 60)
    stop_scheduler()
    sched = start_scheduler()
    assert sched is not None
    assert sched.running
    stop_scheduler()


def test_job_sync_happy_path(monkeypatch) -> None:
    class DummyResult:
        fetched = 1
        upserted = 1

    class DummyFifo:
        lots_created = 1

    class DummySession:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("portmetrics.scheduler.settings.ghostfolio_url", "http://gf")
    monkeypatch.setattr("portmetrics.scheduler.settings.ghostfolio_access_token", "tok")
    monkeypatch.setattr("portmetrics.scheduler.get_engine", lambda: object())
    monkeypatch.setattr("portmetrics.scheduler.GhostfolioClient", lambda *a, **k: object())
    monkeypatch.setattr("portmetrics.scheduler.session_scope", lambda _e: DummySession())
    monkeypatch.setattr(
        "portmetrics.scheduler.sync_ghostfolio_activities",
        lambda *_a, **_k: DummyResult(),
    )
    monkeypatch.setattr("portmetrics.scheduler.rebuild_lots", lambda *_a, **_k: DummyFifo())
    monkeypatch.setattr("portmetrics.scheduler.rebuild_metrics_daily", lambda *_a, **_k: 3)
    job_sync_and_rebuild()


def test_job_rebuild_metrics(monkeypatch) -> None:
    class DummySession:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("portmetrics.scheduler.get_engine", lambda: object())
    monkeypatch.setattr("portmetrics.scheduler.session_scope", lambda _e: DummySession())
    monkeypatch.setattr("portmetrics.scheduler.rebuild_metrics_daily", lambda *_a, **_k: 2)
    job_rebuild_metrics()


def test_configure_logging_with_tmpdir(monkeypatch, tmp_path: Path) -> None:
    import logging

    # Reset handlers so configure_logging runs fully.
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    monkeypatch.setattr("portmetrics.logging_setup.settings.log_dir", str(tmp_path))
    monkeypatch.setattr("portmetrics.logging_setup.settings.log_level", "INFO")
    configure_logging()
    assert (tmp_path / "portmetrics.log").exists() or any(
        isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers
    )
    # Second call is a no-op when handlers exist.
    configure_logging()
