from typing import Any, cast

import pytest
from sqlalchemy import Engine

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
