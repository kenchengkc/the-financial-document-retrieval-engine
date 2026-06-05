from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase

from apps.api.app.config import get_settings


class Base(DeclarativeBase):  # type: ignore[misc]
    """Base class for SQLAlchemy models added in later phases."""


def create_db_engine(database_url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine without connecting at import time."""

    return create_engine(database_url or get_settings().database_url, pool_pre_ping=True)
