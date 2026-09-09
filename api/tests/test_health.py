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
    assert body["version"] == "0.1.0"


def test_api_version() -> None:
    client = TestClient(app)
    response = client.get("/api/version")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "0.1.0"
    assert body["repository"] == "https://github.com/MrMoep/PortMetrics"


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


def test_staging_sync_requires_config(monkeypatch) -> None:
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(paperless_url=None, paperless_token=None),
    )

    def override_db():
        yield MagicMock()

    app.dependency_overrides[main_module.get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post("/api/staging/sync")
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_staging_list_empty(engine) -> None:
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
        response = client.get("/api/staging")
        assert response.status_code == 200
        assert response.json() == {"count": 0, "items": []}
    finally:
        app.dependency_overrides.clear()


def test_webhook_requires_secret_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(paperless_webhook_secret=None),
    )

    def override_db():
        yield MagicMock()

    app.dependency_overrides[main_module.get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post("/api/webhooks/paperless", json={"document_id": 1})
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_webhook_rejects_bad_secret(monkeypatch) -> None:
    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(paperless_webhook_secret="correct"),
    )

    def override_db():
        yield MagicMock()

    app.dependency_overrides[main_module.get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/webhooks/paperless",
            json={"document_id": 1},
            headers={"X-PortMetrics-Secret": "wrong"},
        )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
