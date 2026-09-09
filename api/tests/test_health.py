from fastapi.testclient import TestClient

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


def test_effective_database_url_prefers_test_url() -> None:
    s = Settings(
        app_env="test",
        database_url="postgresql://x/prod",
        test_database_url="postgresql://x/test",
    )
    assert s.effective_database_url.endswith("/test")


def test_effective_database_url_prod_uses_database_url() -> None:
    s = Settings(
        app_env="production",
        database_url="postgresql://x/prod",
        test_database_url="postgresql://x/test",
    )
    assert s.effective_database_url.endswith("/prod")
