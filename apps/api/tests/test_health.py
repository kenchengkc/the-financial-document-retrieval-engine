import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app import main
from apps.api.app.models import Chunk, Company


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
