"""Application settings loaded from the environment / ``.env``."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration.

    Values come from environment variables (or a local ``.env``). Defaults are
    development-friendly; production overrides them via the environment.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://aries:aries@localhost:5432/aries"

    # News API (gnews.io)
    gnews_api_key: str = ""
    gnews_base_url: str = "https://gnews.io/api/v4"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-nano"

    # Background analysis behavior
    insights_max_concurrency: int = 4
    insights_stale_after_seconds: int = 120

    # News query cache (protects the 100 requests/day free-tier quota)
    news_cache_ttl_seconds: int = 300

    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _ensure_async_driver(cls, value: str) -> str:
        """Coerce a platform-provided URL to the async (asyncpg) driver.

        Managed hosts (Render, Railway, Heroku, ...) inject ``postgres://`` or
        ``postgresql://`` URLs, but SQLAlchemy's async engine needs
        ``postgresql+asyncpg://``. URLs that already specify a driver are left
        untouched.

        Args:
            value: The configured database URL.

        Returns:
            The URL with an async driver scheme.
        """
        if value.startswith("postgres://"):
            value = "postgresql://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            value = "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Returns:
        The cached :class:`Settings` instance.
    """
    return Settings()
