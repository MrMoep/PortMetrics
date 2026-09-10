from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from portmetrics.config import get_settings, normalize_database_url
from portmetrics.db.models import SCHEMA


def test_alembic_upgrade_creates_schema(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    url = normalize_database_url(database_url)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    get_settings.cache_clear()

    try:
        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not available: {exc}")

    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(cfg, "head")

    inspector = inspect(engine)
    tables = set(inspector.get_table_names(schema=SCHEMA))
    assert {
        "activities",
        "lots",
        "lot_consumptions",
        "price_snapshots",
        "metrics_daily",
        "document_links",
        "staging_imports",
        "sync_state",
        "app_settings",
        "asset_identifiers",
    }.issubset(tables)

    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
    engine.dispose()
    get_settings.cache_clear()
