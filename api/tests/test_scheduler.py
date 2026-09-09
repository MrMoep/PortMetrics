from __future__ import annotations

from portmetrics.scheduler import build_scheduler, job_sync_and_rebuild


def test_build_scheduler_registers_jobs() -> None:
    scheduler = build_scheduler()
    ids = {job.id for job in scheduler.get_jobs()}
    assert ids == {"sync_ghostfolio", "rebuild_metrics"}


def test_job_sync_skips_without_config(monkeypatch, caplog) -> None:
    monkeypatch.setattr("portmetrics.scheduler.settings.ghostfolio_url", None)
    monkeypatch.setattr("portmetrics.scheduler.settings.ghostfolio_access_token", None)
    with caplog.at_level("DEBUG"):
        job_sync_and_rebuild()
    assert "Skipping scheduled sync" in caplog.text
