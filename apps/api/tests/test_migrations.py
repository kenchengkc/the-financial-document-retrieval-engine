from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from apps.api.app import models  # noqa: F401
from apps.api.app.db import Base

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_TABLES = set(Base.metadata.tables)


def test_initial_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    database_path = tmp_path / "fdre.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    config = Config(REPO_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    migrated_tables = set(inspect(engine).get_table_names())
    assert not EXPECTED_TABLES - migrated_tables

    command.downgrade(config, "base")

    remaining_tables = set(inspect(engine).get_table_names())
    assert EXPECTED_TABLES.isdisjoint(remaining_tables)
