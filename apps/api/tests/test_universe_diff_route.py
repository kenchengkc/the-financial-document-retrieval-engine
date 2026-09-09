from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
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


def test_universe_diff_route_reports_membership_and_identity_changes(tmp_path: Path) -> None:
    database_path = tmp_path / "hu3-diff.db"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    _seed(engine)

    app = create_app()

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    client = TestClient(app)
    response = client.get(
        "/research/universe/sp500/diff",
        params={"from": "2020-01-15", "to": "2021-01-01"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "fdre-hu3-universe-diff-v1"
    assert payload["summary"] == {
        "from_count": 2,
        "to_count": 2,
        "added_count": 1,
        "removed_count": 1,
        "changed_count": 1,
        "retained_count": 1,
    }
    assert payload["added"][0]["security_id"] == 3
    assert payload["removed"][0]["security_id"] == 2
    assert payload["changed"][0]["security_id"] == 1
    assert payload["changed"][0]["before"]["symbol"] == "ABC"
    assert payload["changed"][0]["after"]["symbol"] == "ABX"
    assert len(payload["from_snapshot_id"]) == 64
    assert len(payload["to_snapshot_id"]) == 64
    engine.dispose()


def _seed(engine: Engine) -> None:
    with Session(engine) as session:
        companies = [
            Company(id=1, ticker="ABX", cik="0000000001", name="ABC Corp", exchange="NYSE"),
            Company(id=2, ticker="DEF", cik="0000000002", name="DEF Corp", exchange="NYSE"),
            Company(id=3, ticker="GHI", cik="0000000003", name="GHI Corp", exchange="NASDAQ"),
        ]
        securities = [
            Security(id=1, company_id=1, security_type="common_stock"),
            Security(id=2, company_id=2, security_type="common_stock"),
            Security(id=3, company_id=3, security_type="common_stock"),
        ]
        session.add_all(companies + securities)
        session.add_all(
            [
                _identity(1, securities[0], "ABC", date(2020, 1, 1), date(2020, 6, 1), "a"),
                _identity(2, securities[0], "ABX", date(2020, 6, 1), None, "b"),
                _identity(3, securities[1], "DEF", date(2020, 1, 1), None, "c"),
                _identity(4, securities[2], "GHI", date(2020, 1, 1), None, "d"),
                _membership(1, securities[0], date(2020, 1, 1), None, "e"),
                _membership(2, securities[1], date(2020, 1, 1), date(2020, 7, 1), "f"),
                _membership(3, securities[2], date(2020, 7, 1), None, "0"),
            ]
        )
        session.commit()


def _identity(
    row_id: int,
    security: Security,
    symbol: str,
    effective_from: date,
    effective_to: date | None,
    source_char: str,
) -> SecurityIdentityPeriod:
    return SecurityIdentityPeriod(
        id=row_id,
        security=security,
        symbol=symbol,
        name=f"{symbol} Corp",
        exchange="NYSE",
        effective_from=effective_from,
        effective_to=effective_to,
        source="test",
        source_observed_at=OBSERVED_AT,
        source_hash=source_char * 64,
        verification_status="verified",
        confidence=1.0,
    )


def _membership(
    row_id: int,
    security: Security,
    effective_from: date,
    effective_to: date | None,
    source_char: str,
) -> UniverseMembership:
    return UniverseMembership(
        id=row_id,
        universe_code="sp500",
        security=security,
        effective_from=effective_from,
        effective_to=effective_to,
        source="test",
        source_observed_at=OBSERVED_AT,
        source_hash=source_char * 64,
        verification_status="verified",
        confidence=1.0,
    )
