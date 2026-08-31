from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Company, Document
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
        security = Security(id=1, company_id=1, security_type="common_stock")
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


def test_empty_pit_universe_cannot_expand_to_all_panel_companies() -> None:
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
        security = Security(id=1, company_id=1, security_type="common_stock")
        session.add_all(
            (
                company,
                security,
                Document(
                    company=company,
                    source_type="sec",
                    form_type="10-K",
                    filing_date=date(2004, 2, 1),
                    period_end_date=date(2003, 12, 31),
                    accepted_at=datetime(2004, 2, 1, tzinfo=UTC),
                    available_at=datetime(2004, 2, 1, tzinfo=UTC),
                    accession_number="unrelated-2003",
                ),
                SecurityIdentityPeriod(
                    id=1,
                    security=security,
                    symbol="ABC",
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
            as_of="2005-06-30",
            query=ResearchPanelQuery(limit=10),
        )

        assert result.universe_snapshot.constituents == ()
        assert result.panel.rows == []
        assert result.panel.query.tickers == []
        assert result.panel.query.as_of is not None
        assert result.panel.query.as_of.date() == date(2005, 6, 30)
    engine.dispose()
