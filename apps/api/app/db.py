from collections.abc import Generator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from apps.api.app.config import get_settings, normalize_database_url

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models added in later phases."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_db_engine(database_url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine without connecting at import time."""

    settings = get_settings()
    normalized_url = normalize_database_url(database_url or settings.database_url)
    engine_options: dict[str, Any] = {"pool_pre_ping": True}
    if normalized_url.startswith("postgresql+psycopg://"):
        engine_options.update(
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
            pool_recycle=settings.database_pool_recycle_seconds,
        )
    return create_engine(normalized_url, **engine_options)


@lru_cache
def get_engine() -> Engine:
    return create_db_engine()


def get_db_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
