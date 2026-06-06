from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase

from apps.api.app.config import get_settings

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

    return create_engine(database_url or get_settings().database_url, pool_pre_ping=True)
