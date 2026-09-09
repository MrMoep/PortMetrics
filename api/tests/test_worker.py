from __future__ import annotations

import pytest

from portmetrics.worker import cmd_sync_ghostfolio, parse_args


def test_parse_args_sync_command() -> None:
    args = parse_args(["sync-ghostfolio"])
    assert args.command == "sync-ghostfolio"


def test_cmd_sync_requires_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("portmetrics.worker.settings.ghostfolio_url", None)
    monkeypatch.setattr("portmetrics.worker.settings.ghostfolio_access_token", None)
    assert cmd_sync_ghostfolio() == 2
