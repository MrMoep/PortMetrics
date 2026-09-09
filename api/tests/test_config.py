from portmetrics.config import Settings, get_settings, normalize_database_url


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
