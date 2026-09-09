from portmetrics.config import Settings, get_settings, normalize_database_url, parse_cors_origins


def test_normalize_database_url_adds_psycopg_driver() -> None:
    assert normalize_database_url("postgresql://x/y").startswith("postgresql+psycopg://")
    assert normalize_database_url("postgres://x/y").startswith("postgresql+psycopg://")
    assert normalize_database_url("postgresql+psycopg://x/y") == "postgresql+psycopg://x/y"


def test_effective_database_url_prefers_test_url() -> None:
    get_settings.cache_clear()
    s = Settings(
        app_env="test",
        database_url="postgresql+psycopg://x/prod",
        test_database_url="postgresql+psycopg://x/test",
    )
    assert s.effective_database_url.endswith("/test")


def test_effective_database_url_prod_uses_database_url() -> None:
    s = Settings(
        app_env="production",
        database_url="postgresql+psycopg://x/prod",
        test_database_url="postgresql+psycopg://x/test",
    )
    assert s.effective_database_url.endswith("/prod")


def test_parse_cors_origins_splits_and_trims() -> None:
    assert parse_cors_origins("") == []
    assert parse_cors_origins(" https://portmetric.mrcarott.de ") == [
        "https://portmetric.mrcarott.de"
    ]
    assert parse_cors_origins(
        "https://portmetric.mrcarott.de, http://localhost:8080"
    ) == ["https://portmetric.mrcarott.de", "http://localhost:8080"]


def test_settings_cors_origin_list() -> None:
    s = Settings(cors_origins="https://portmetric.mrcarott.de")
    assert s.cors_origin_list == ["https://portmetric.mrcarott.de"]


def test_webhook_secret_matches() -> None:
    from portmetrics.config import webhook_secret_matches

    assert webhook_secret_matches("abc", "abc") is True
    assert webhook_secret_matches("abc", "abd") is False
    assert webhook_secret_matches(None, "abc") is False
    assert webhook_secret_matches("abc", None) is False
