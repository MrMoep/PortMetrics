from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import portmetrics.main as main_module
from portmetrics.config import Settings
from portmetrics.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "env" in body


def test_api_health() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_sync_requires_config(monkeypatch) -> None:
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(ghostfolio_url=None, ghostfolio_access_token=None),
    )

    def override_db():
        yield MagicMock()

    app.dependency_overrides[main_module.get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post("/api/sync/ghostfolio")
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_sync_status_empty(engine) -> None:
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
        client = TestClient(app)
        response = client.get("/api/sync/status")
        assert response.status_code == 200
        body = response.json()
        assert body["activity_count"] == 0
        assert body["last_sync_at"] is None
    finally:
        app.dependency_overrides.clear()
