import tomllib
from collections.abc import Generator
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app import main
from apps.api.app.db import get_db_session
from apps.api.app.models import Chunk, Company

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_health_returns_ok() -> None:
    client = TestClient(main.create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_ok_when_database_is_available() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
    )
    app = main.create_app()

    def override_db_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_503_when_database_is_unavailable() -> None:
    app = main.create_app()

    class FailingSession:
        def execute(self, statement: object) -> None:
            del statement
            raise RuntimeError("database unavailable")

    def override_db_session() -> Generator[Session, None, None]:
        yield cast(Session, FailingSession())

    app.dependency_overrides[get_db_session] = override_db_session
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}


def test_vercel_demo_database_initialization_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
    )
    monkeypatch.setattr(main, "get_engine", lambda: engine)

    main._initialize_demo_database()
    main._initialize_demo_database()

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Company)) == 1
        assert (session.scalar(select(func.count()).select_from(Chunk)) or 0) > 0


def test_railway_separates_schema_migration_from_traffic_admission() -> None:
    config = tomllib.loads((REPO_ROOT / "railway.toml").read_text())

    deploy = config["deploy"]
    assert deploy["preDeployCommand"] == "alembic upgrade head"
    assert "scripts.research.refresh_research_console_metrics" not in deploy["preDeployCommand"]
    assert deploy["healthcheckPath"] == "/ready"
    assert "alembic" not in deploy["startCommand"]
    assert "uvicorn" in deploy["startCommand"]
    assert deploy["startCommand"].startswith("sh -c ")
    assert "${PORT:-8000}" in deploy["startCommand"]
