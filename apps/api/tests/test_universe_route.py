from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.db import Base, get_db_session
from apps.api.app.main import create_app
from apps.api.app.models.companies import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)

OBSERVED_AT = datetime(2026, 8, 30, 16, 0, tzinfo=UTC)


def _seed(database_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(
            id=1,
            ticker="ABC",
            cik="0000000001",
            name="ABC Corp",
            exchange="NYSE",
        )
        security = Security(id=1, company=company, security_type="common_stock")
        session.add_all(
            (
                company,
                security,
                SecurityIdentityPeriod(
                    id=1,
                    security=security,
                    symbol="ABC",
                    name="ABC Corp",
                    exchange="NYSE",
                    effective_from=date(2020, 1, 1),
                    source="test",
                    source_observed_at=OBSERVED_AT,
                    source_hash="a" * 64,
                    verification_status="verified",
                    confidence=1.0,
                ),
                UniverseMembership(
                    id=1,
                    universe_code="sp500",
                    security=security,
                    effective_from=date(2020, 1, 1),
                    source="test",
                    source_observed_at=OBSERVED_AT,
                    source_hash="b" * 64,
                    verification_status="verified",
                    confidence=1.0,
                ),
            )
        )
        session.commit()
    engine.dispose()


def test_universe_route_returns_replayable_pit_snapshot(tmp_path: Path) -> None:
    database_path = tmp_path / "hu3.db"
    _seed(database_path)
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    app = create_app()

    def override_session():  # type: ignore[no-untyped-def]
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    client = TestClient(app)

    response = client.get("/research/universe/sp500", params={"as_of": "2021-01-01"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["universe_code"] == "sp500"
    assert payload["as_of"] == "2021-01-01"
    assert payload["constituent_count"] == 1
    assert payload["constituents"][0]["symbol"] == "ABC"
    assert len(payload["snapshot_id"]) == 64
    engine.dispose()
