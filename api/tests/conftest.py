from __future__ import annotations

import os
from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import portmetrics.main as main_module
from portmetrics.config import normalize_database_url
from portmetrics.db.models import SCHEMA, Base
from portmetrics.db.session import ensure_schema
from portmetrics.main import app


@pytest.fixture()
def database_url() -> str:
    raw = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://portmetrics:portmetrics@localhost:5432/portmetrics_test",
        ),
    )
    return normalize_database_url(raw)


@pytest.fixture()
def engine(database_url: str):
    try:
        eng = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - skip when local PG is unavailable
        pytest.skip(f"PostgreSQL not available: {exc}")

    ensure_schema(eng, SCHEMA)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db_session(engine) -> Generator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def sample_activity_payload() -> dict:
    return {
        "id": str(uuid4()),
        "accountId": "acc-1",
        "currency": "EUR",
        "date": "2024-01-15T00:00:00.000Z",
        "fee": 1.5,
        "quantity": 10,
        "type": "BUY",
        "unitPrice": 100.25,
        "comment": "test buy",
        "SymbolProfile": {
            "symbol": "VWCE.DE",
            "isin": "IE00BK5BQT80",
            "dataSource": "YAHOO",
        },
    }


@pytest.fixture()
def api_db(engine) -> Generator[tuple[TestClient, sessionmaker]]:
    """TestClient with get_db overridden to the test engine."""
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_db():
        session = SessionLocal()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    app.dependency_overrides[main_module.get_db] = override_db
    try:
        yield TestClient(app), SessionLocal
    finally:
        app.dependency_overrides.clear()
