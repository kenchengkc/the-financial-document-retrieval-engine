from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(value: str) -> str:
    """Normalize provider-issued bare Postgres URLs to FDRE's psycopg v3 driver."""

    if value.startswith("postgresql+"):
        return value
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://") :]
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://") :]
    return value


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    app_name: str = "FDRE API"
    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="info", alias="LOG_LEVEL")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_expensive_requests_per_window: int = Field(
        default=30,
        ge=1,
        le=10_000,
        alias="API_EXPENSIVE_REQUESTS_PER_WINDOW",
    )
    api_expensive_window_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        alias="API_EXPENSIVE_WINDOW_SECONDS",
    )
    api_expensive_max_callers: int = Field(
        default=2048,
        ge=1,
        le=100_000,
        alias="API_EXPENSIVE_MAX_CALLERS",
    )
    api_expensive_max_in_flight: int = Field(
        default=8,
        ge=1,
        le=256,
        alias="API_EXPENSIVE_MAX_IN_FLIGHT",
    )
    api_overload_retry_after_seconds: int = Field(
        default=1,
        ge=1,
        le=300,
        alias="API_OVERLOAD_RETRY_AFTER_SECONDS",
    )
    database_url: str = Field(
        default="postgresql+psycopg://fdre:fdre@localhost:5432/fdre",
        alias="DATABASE_URL",
    )
    database_pool_size: int = Field(default=5, ge=1, le=50, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=5, ge=0, le=50, alias="DATABASE_MAX_OVERFLOW")
    database_pool_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=120,
        alias="DATABASE_POOL_TIMEOUT_SECONDS",
    )
    database_pool_recycle_seconds: int = Field(
        default=1800,
        ge=0,
        le=86400,
        alias="DATABASE_POOL_RECYCLE_SECONDS",
    )
    database_statement_timeout_ms: int = Field(
        default=30_000,
        ge=0,
        le=300_000,
        alias="DATABASE_STATEMENT_TIMEOUT_MS",
    )
    cors_origins: str = Field(
        default=(
            "https://thefdre.com,https://www.thefdre.com,"
            "http://localhost:3000,http://127.0.0.1:3000"
        ),
        alias="CORS_ORIGINS",
    )
    sec_user_agent: str | None = Field(default=None, alias="SEC_USER_AGENT")
    sec_cache_dir: str = Field(default="data/cache/sec", alias="SEC_CACHE_DIR")
    sec_rate_limit_requests_per_second: int = Field(
        default=5,
        alias="SEC_RATE_LIMIT_REQUESTS_PER_SECOND",
    )
    embedding_provider: str = Field(default="local_hash", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="local-hash-v1", alias="EMBEDDING_MODEL")
    embedding_dimensions: int | None = Field(
        default=None,
        ge=1,
        alias="EMBEDDING_DIMENSIONS",
    )
    embedding_batch_size: int = Field(default=64, ge=1, le=1000, alias="EMBEDDING_BATCH_SIZE")
    embedding_requests_per_minute: int | None = Field(
        default=None,
        ge=1,
        alias="EMBEDDING_REQUESTS_PER_MINUTE",
    )
    embedding_tokens_per_minute: int | None = Field(
        default=None,
        ge=1,
        alias="EMBEDDING_TOKENS_PER_MINUTE",
    )
    embedding_concurrency: int = Field(default=8, ge=1, le=64, alias="EMBEDDING_CONCURRENCY")
    embedding_cost_per_million_tokens: float = Field(
        default=0.0,
        ge=0.0,
        alias="EMBEDDING_COST_PER_MILLION_TOKENS",
    )
    sparse_provider: str = Field(default="postgres", alias="SPARSE_PROVIDER")
    reranker_provider: str = Field(default="none", alias="RERANKER_PROVIDER")
    reranker_model: str = Field(default="rerank-2.5", alias="RERANKER_MODEL")
    rerank_top_n: int = Field(default=50, alias="RERANK_TOP_N")
    min_rerank_score: float = Field(default=0.0, ge=0.0, alias="MIN_RERANK_SCORE")
    answer_generator: str = Field(default="extractive", alias="ANSWER_GENERATOR")
    answer_top_k: int = Field(default=8, ge=1, le=50, alias="ANSWER_TOP_K")
    min_evidence_chunks: int = Field(default=2, alias="MIN_EVIDENCE_CHUNKS")
    min_retrieval_score: float = Field(default=0.2, alias="MIN_RETRIEVAL_SCORE")
    neighbor_expansion_window: int = Field(
        default=1, ge=0, le=5, alias="NEIGHBOR_EXPANSION_WINDOW"
    )
    answer_cache_ttl_seconds: int = Field(
        default=21600, ge=0, alias="ANSWER_CACHE_TTL_SECONDS"
    )
    research_cache_ttl_seconds: int = Field(
        default=21600, ge=0, alias="RESEARCH_CACHE_TTL_SECONDS"
    )
    company_reference_cache_ttl_seconds: int = Field(
        default=300,
        ge=0,
        le=86_400,
        alias="COMPANY_REFERENCE_CACHE_TTL_SECONDS",
    )
    company_reference_cache_stale_if_error_seconds: int = Field(
        default=3600,
        ge=0,
        le=86_400,
        alias="COMPANY_REFERENCE_CACHE_STALE_IF_ERROR_SECONDS",
    )
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    voyage_api_key: str | None = Field(default=None, alias="VOYAGE_API_KEY")

    @field_validator("database_url")
    @classmethod
    def _ensure_psycopg_driver(cls, value: str) -> str:
        """Normalize bare Postgres URLs (e.g. Railway's) to the psycopg driver."""

        return normalize_database_url(value)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
