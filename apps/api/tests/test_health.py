import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app import main
from apps.api.app.models import Chunk, Company

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_health_returns_ok() -> None:
    client = TestClient(main.create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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


def test_railway_runs_migrations_before_starting_the_api() -> None:
    config = tomllib.loads((REPO_ROOT / "railway.toml").read_text())

    assert config["deploy"]["preDeployCommand"] == "alembic upgrade head"
    assert "alembic" not in config["deploy"]["startCommand"]
    assert "uvicorn" in config["deploy"]["startCommand"]
    assert config["deploy"]["startCommand"].startswith("sh -c ")
    assert "${PORT:-8000}" in config["deploy"]["startCommand"]
