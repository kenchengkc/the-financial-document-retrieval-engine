from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    app_name: str = "FDRE API"
    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="info", alias="LOG_LEVEL")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    database_url: str = Field(
        default="postgresql+psycopg://fdre:fdre@localhost:5432/fdre",
        alias="DATABASE_URL",
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
    sparse_provider: str = Field(default="postgres", alias="SPARSE_PROVIDER")
    reranker_provider: str = Field(default="none", alias="RERANKER_PROVIDER")
    reranker_model: str = Field(default="rerank-2.5", alias="RERANKER_MODEL")
    rerank_top_n: int = Field(default=50, alias="RERANK_TOP_N")
    min_rerank_score: float = Field(default=0.0, ge=0.0, alias="MIN_RERANK_SCORE")
    answer_generator: str = Field(default="mock", alias="ANSWER_GENERATOR")
    answer_top_k: int = Field(default=8, ge=1, le=50, alias="ANSWER_TOP_K")
    min_evidence_chunks: int = Field(default=2, alias="MIN_EVIDENCE_CHUNKS")
    min_retrieval_score: float = Field(default=0.2, alias="MIN_RETRIEVAL_SCORE")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    voyage_api_key: str | None = Field(default=None, alias="VOYAGE_API_KEY")

    @field_validator("database_url")
    @classmethod
    def _ensure_psycopg_driver(cls, value: str) -> str:
        """Normalize bare Postgres URLs (e.g. Railway's) to the psycopg driver."""

        if value.startswith("postgresql+"):
            return value
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://") :]
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
