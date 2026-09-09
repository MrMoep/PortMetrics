from __future__ import annotations

from portmetrics.build_info import display_version


def test_display_version_default(monkeypatch) -> None:
    monkeypatch.delenv("PORTMETRICS_CHANNEL", raising=False)
    monkeypatch.delenv("PORTMETRICS_BUILT_AT", raising=False)
    assert display_version() == "0.2.0"


def test_display_version_dev_with_timestamp(monkeypatch) -> None:
    monkeypatch.setenv("PORTMETRICS_CHANNEL", "dev")
    monkeypatch.setenv("PORTMETRICS_BUILT_AT", "2026-09-09 23:18")
    assert display_version() == "0.2.0-dev · 2026-09-09 23:18"


def test_display_version_dev_without_timestamp(monkeypatch) -> None:
    monkeypatch.setenv("PORTMETRICS_CHANNEL", "dev")
    monkeypatch.delenv("PORTMETRICS_BUILT_AT", raising=False)
    assert display_version() == "0.2.0-dev"


def test_api_version_includes_build_metadata(monkeypatch) -> None:
    monkeypatch.setenv("PORTMETRICS_CHANNEL", "dev")
    monkeypatch.setenv("PORTMETRICS_BUILT_AT", "2026-09-09 23:18")
    monkeypatch.setenv("PORTMETRICS_GIT_SHA", "abc1234")

    from fastapi.testclient import TestClient

    from portmetrics.main import app

    client = TestClient(app)
    body = client.get("/api/version").json()
    assert body["version"] == "0.2.0-dev · 2026-09-09 23:18"
    assert body["channel"] == "dev"
    assert body["built_at"] == "2026-09-09 23:18"
    assert body["git_sha"] == "abc1234"
    assert body["package_version"] == "0.2.0"
