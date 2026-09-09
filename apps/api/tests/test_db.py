import os
from typing import Any, cast

import pytest
from sqlalchemy import Engine, create_engine as sqlalchemy_create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.api.app import db
from apps.api.app.config import Settings


def _capture_create_engine(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_create_engine(url: str, **kwargs: Any) -> Engine:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return cast(Engine, object())

    monkeypatch.setattr(db, "create_engine", fake_create_engine)
    return captured


def test_postgres_engine_uses_explicit_pool_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        DATABASE_URL="postgresql://user:pass@example.test/fdre",
        DATABASE_POOL_SIZE=7,
        DATABASE_MAX_OVERFLOW=3,
        DATABASE_POOL_TIMEOUT_SECONDS=12,
        DATABASE_POOL_RECYCLE_SECONDS=900,
    )
    monkeypatch.setattr(db, "get_settings", lambda: settings)
    captured = _capture_create_engine(monkeypatch)

    db.create_db_engine()

    assert captured["url"] == "postgresql+psycopg://user:pass@example.test/fdre"
    assert captured["kwargs"] == {
        "pool_pre_ping": True,
        "pool_size": 7,
        "max_overflow": 3,
        "pool_timeout": 12,
        "pool_recycle": 900,
    }


def test_sqlite_engine_does_not_receive_postgres_pool_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db, "get_settings", Settings)
    captured = _capture_create_engine(monkeypatch)

    db.create_db_engine("sqlite+pysqlite:///:memory:")

    assert captured["url"] == "sqlite+pysqlite:///:memory:"
    assert captured["kwargs"] == {"pool_pre_ping": True}


def test_request_session_carries_interactive_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = sqlalchemy_create_engine("sqlite+pysqlite:///:memory:")
    settings = Settings(DATABASE_STATEMENT_TIMEOUT_MS=4321)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(db, "get_settings", lambda: settings)

    dependency = db.get_db_session()
    session = next(dependency)
    try:
        assert session.info[db.REQUEST_STATEMENT_TIMEOUT_INFO_KEY] == 4321
    finally:
        dependency.close()
        engine.dispose()


def test_postgres_request_statement_timeout_cancels_and_does_not_leak() -> None:
    database_url = os.environ.get("FDRE_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("FDRE_POSTGRES_TEST_URL is required for PostgreSQL timeout verification")

    engine = sqlalchemy_create_engine(database_url, pool_size=1, max_overflow=0)
    try:
        with Session(engine) as baseline_session:
            baseline_timeout = str(baseline_session.scalar(text("SHOW statement_timeout")))

        with Session(
            engine,
            info={db.REQUEST_STATEMENT_TIMEOUT_INFO_KEY: 25},
        ) as request_session:
            with pytest.raises(DBAPIError):
                request_session.execute(text("SELECT pg_sleep(0.2)")).all()
            request_session.rollback()
            assert request_session.scalar(text("SELECT 1")) == 1

        with Session(engine) as operational_session:
            observed_timeout = str(
                operational_session.scalar(text("SHOW statement_timeout"))
            )
            assert observed_timeout == baseline_timeout
    finally:
        engine.dispose()
