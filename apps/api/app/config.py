from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "FDRE API"
    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="info", alias="LOG_LEVEL")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    database_url: str = Field(
        default="postgresql+psycopg://fdre:fdre@localhost:5432/fdre",
        alias="DATABASE_URL",
    )
    sec_user_agent: str | None = Field(default=None, alias="SEC_USER_AGENT")
    sec_cache_dir: str = Field(default="data/cache/sec", alias="SEC_CACHE_DIR")
    sec_rate_limit_requests_per_second: int = Field(
        default=5,
        alias="SEC_RATE_LIMIT_REQUESTS_PER_SECOND",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
