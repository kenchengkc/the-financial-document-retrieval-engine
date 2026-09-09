from collections.abc import Generator
from functools import lru_cache
from typing import Any

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, SessionTransaction

from apps.api.app.config import get_settings, normalize_database_url

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
REQUEST_STATEMENT_TIMEOUT_INFO_KEY = "fdre_request_statement_timeout_ms"


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models added in later phases."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@event.listens_for(Session, "after_begin")
def _apply_request_statement_timeout(
    session: Session,
    transaction: SessionTransaction,
    connection: Connection,
) -> None:
    """Apply the API-only timeout to every request transaction using SET LOCAL."""

    del transaction
    timeout_ms = session.info.get(REQUEST_STATEMENT_TIMEOUT_INFO_KEY)
    if connection.dialect.name != "postgresql" or not isinstance(timeout_ms, int):
        return
    if timeout_ms <= 0:
        return
    connection.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_ms}")


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
    settings = get_settings()
    with Session(
        get_engine(),
        info={
            REQUEST_STATEMENT_TIMEOUT_INFO_KEY: settings.database_statement_timeout_ms,
        },
    ) as session:
        try:
            yield session
        finally:
            if session.in_transaction():
                session.rollback()
