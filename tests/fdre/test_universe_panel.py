from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models.companies import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.research.panel import ResearchPanelQuery
from fdre.research.universe_panel import build_research_panel_for_universe

OBSERVED_AT = datetime(2026, 8, 30, 16, 0, tzinfo=UTC)


def test_panel_composition_uses_pit_universe_and_persists_snapshot_identity() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
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
                    symbol="OLDABC",
                    name="ABC Corp",
                    exchange="NYSE",
                    effective_from=date(2010, 1, 1),
                    source="identity-source",
                    source_observed_at=OBSERVED_AT,
                    source_hash="a" * 64,
                    verification_status="verified",
                    confidence=1.0,
                ),
                UniverseMembership(
                    id=1,
                    universe_code="sp500",
                    security=security,
                    effective_from=date(2010, 1, 1),
                    source="membership-source",
                    source_observed_at=OBSERVED_AT,
                    source_hash="b" * 64,
                    verification_status="verified",
                    confidence=1.0,
                ),
            )
        )
        session.commit()

        result = build_research_panel_for_universe(
            session,
            "sp500",
            as_of="2012-06-30",
            query=ResearchPanelQuery(limit=10),
        )

        assert result.universe_snapshot.constituents[0].symbol == "OLDABC"
        assert result.panel.query.tickers == ["ABC"]
        assert result.panel.query.as_of is not None
        assert result.panel.query.as_of.date() == date(2012, 6, 30)
        assert len(result.universe_snapshot.snapshot_id) == 64
    engine.dispose()
