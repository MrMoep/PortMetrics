from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql://portmetrics:portmetrics@localhost:5432/portmetrics_test"
    test_database_url: str | None = None
    log_level: str = "INFO"
    ghostfolio_url: str | None = None
    ghostfolio_access_token: str | None = None
    paperless_url: str | None = None
    paperless_token: str | None = None

    @property
    def effective_database_url(self) -> str:
        """Prefer TEST_DATABASE_URL in test/dev so production is never hit by pytest."""
        if self.app_env in {"test", "development"} and self.test_database_url:
            return self.test_database_url
        return self.database_url


settings = Settings()
