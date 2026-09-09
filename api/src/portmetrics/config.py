from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Ensure SQLAlchemy uses the psycopg3 driver."""
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = (
        "postgresql+psycopg://portmetrics:portmetrics@localhost:5432/portmetrics_test"
    )
    test_database_url: str | None = None
    log_level: str = "INFO"
    ghostfolio_url: str | None = None
    ghostfolio_access_token: str | None = None
    paperless_url: str | None = None
    paperless_token: str | None = None
    default_tax_rate: str = "0.26375"  # DE Abgeltungsteuer + Soli (Schätzung)
    web_dist_dir: str = "/app/web/dist"

    @property
    def effective_database_url(self) -> str:
        """Prefer TEST_DATABASE_URL in test/dev so production is never hit by pytest."""
        if self.app_env in {"test", "development"} and self.test_database_url:
            return normalize_database_url(self.test_database_url)
        return normalize_database_url(self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
