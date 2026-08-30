from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from scripts.bootstrap_current_security_master import (
    bootstrap_current_security_master,
    load_current_security_bootstrap,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.db import Base
from apps.api.app.models.companies import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _write_snapshot(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "source": "wikipedia:List_of_S%26P_500_companies + fdre listed_companies.json",
                "generated_at": "2026-06-08T13:50:33.693552+00:00",
                "constituent_count": 4,
                "primary_ticker_count": 2,
                "missing_from_catalog": ["CBOE"],
                "aliases": {
                    "GOOG": "GOOG",
                    "GOOGL": "GOOG",
                    "MSFT": "MSFT",
                },
                "primary_tickers": ["GOOG", "MSFT"],
            }
        ),
        encoding="utf-8",
    )


def _seed_companies(session: Session) -> None:
    session.add_all(
        [
            Company(
                ticker="GOOG",
                cik="0001652044",
                name="Alphabet Inc.",
                exchange="NASDAQ",
            ),
            Company(
                ticker="MSFT",
                cik="0000789019",
                name="Microsoft Corporation",
                exchange="NASDAQ",
            ),
        ]
    )
    session.commit()


def test_bootstrap_creates_distinct_current_securities_without_memberships(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "sp500.json"
    _write_snapshot(snapshot_path)
    bootstrap = load_current_security_bootstrap(snapshot_path)
    engine = _engine()

    with Session(engine) as session:
        _seed_companies(session)
        report = bootstrap_current_security_master(session, bootstrap, apply=True)
        session.commit()

        securities = tuple(session.scalars(select(Security).order_by(Security.id)))
        periods = tuple(
            session.scalars(
                select(SecurityIdentityPeriod).order_by(SecurityIdentityPeriod.symbol)
            )
        )
        membership_count = int(
            session.scalar(select(func.count()).select_from(UniverseMembership)) or 0
        )
        goog_company_id = int(
            session.scalar(select(Company.id).where(Company.ticker == "GOOG")) or 0
        )

    assert len(securities) == 3
    assert sum(security.company_id == goog_company_id for security in securities) == 2
    assert [period.symbol for period in periods] == ["GOOG", "GOOGL", "MSFT"]
    assert all(period.effective_from == date(2026, 6, 8) for period in periods)
    assert all(period.effective_to is None for period in periods)
    assert all(period.verification_status == "provisional" for period in periods)
    assert membership_count == 0
    assert report["planned_security_count"] == 3
    assert report["created_security_count"] == 3
    assert report["created_identity_period_count"] == 3
    assert report["historical_memberships_written"] == 0
    assert report["missing_catalog_symbols"] == ["CBOE"]


def test_bootstrap_is_idempotent(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "sp500.json"
    _write_snapshot(snapshot_path)
    bootstrap = load_current_security_bootstrap(snapshot_path)
    engine = _engine()

    with Session(engine) as session:
        _seed_companies(session)
        first = bootstrap_current_security_master(session, bootstrap, apply=True)
        session.commit()
        second = bootstrap_current_security_master(session, bootstrap, apply=True)
        session.commit()
        security_count = int(session.scalar(select(func.count()).select_from(Security)) or 0)
        identity_count = int(
            session.scalar(select(func.count()).select_from(SecurityIdentityPeriod)) or 0
        )

    assert first["created_security_count"] == 3
    assert second["planned_security_count"] == 0
    assert second["created_security_count"] == 0
    assert second["reused_identity_period_count"] == 3
    assert security_count == 3
    assert identity_count == 3


def test_bootstrap_dry_run_leaves_database_unchanged(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "sp500.json"
    _write_snapshot(snapshot_path)
    bootstrap = load_current_security_bootstrap(snapshot_path)
    engine = _engine()

    with Session(engine) as session:
        _seed_companies(session)
        report = bootstrap_current_security_master(session, bootstrap, apply=False)
        session.rollback()
        security_count = int(session.scalar(select(func.count()).select_from(Security)) or 0)
        identity_count = int(
            session.scalar(select(func.count()).select_from(SecurityIdentityPeriod)) or 0
        )

    assert report["applied"] is False
    assert report["planned_security_count"] == 3
    assert report["created_security_count"] == 0
    assert security_count == 0
    assert identity_count == 0


def test_bootstrap_fails_closed_when_symbol_points_to_wrong_company(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "sp500.json"
    _write_snapshot(snapshot_path)
    bootstrap = load_current_security_bootstrap(snapshot_path)
    engine = _engine()

    with Session(engine) as session:
        _seed_companies(session)
        msft = session.scalar(select(Company).where(Company.ticker == "MSFT"))
        assert msft is not None
        security = Security(company_id=msft.id, security_type="common_stock")
        session.add(security)
        session.flush()
        session.add(
            SecurityIdentityPeriod(
                security_id=security.id,
                symbol="GOOG",
                name="Wrong Company",
                exchange="NASDAQ",
                effective_from=date(2026, 6, 8),
                effective_to=None,
                source="test",
                source_observed_at=datetime(2026, 6, 8, 13, 50, tzinfo=UTC),
                source_hash="a" * 64,
                verification_status="verified",
                confidence=1.0,
            )
        )
        session.commit()

        with pytest.raises(ValueError, match="wrong production company"):
            bootstrap_current_security_master(session, bootstrap, apply=True)


def test_bootstrap_rejects_inconsistent_alias_targets(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "sp500.json"
    _write_snapshot(snapshot_path)
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["primary_tickers"] = ["GOOG"]
    payload["primary_ticker_count"] = 1
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="alias targets are inconsistent"):
        load_current_security_bootstrap(snapshot_path)
