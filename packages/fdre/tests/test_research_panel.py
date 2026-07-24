from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Company, Document, DocumentElement, FinancialFact
from fdre.research.panel import (
    ResearchPanelQuery,
    ResearchPanelRow,
    build_research_panel,
    serialize_research_panel,
    validate_point_in_time_rows,
    write_research_panel,
)


def _add_document(
    company: Company,
    *,
    accession: str,
    period_end: date,
    available_at: datetime,
    revenue: Decimal,
    operating_income: Decimal,
    passages: list[str],
) -> Document:
    document = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        filing_date=available_at.date(),
        period_end_date=period_end,
        accepted_at=available_at,
        available_at=available_at,
        accession_number=accession,
    )
    for order, passage in enumerate(passages, start=1):
        document.elements.append(
            DocumentElement(
                element_type="text",
                section="Risk Factors",
                text=passage,
                reading_order=order,
            )
        )
    for metric, concept, value in (
        ("revenue", "Revenues", revenue),
        ("operating_income", "OperatingIncomeLoss", operating_income),
    ):
        company.financial_facts.append(
            FinancialFact(
                document=document,
                ticker=company.ticker,
                fact_key=f"{accession}-{metric}",
                taxonomy="us-gaap",
                concept=concept,
                canonical_metric=metric,
                value=value,
                unit="USD",
                period_start=date(period_end.year, 1, 1),
                period_end=period_end,
                period_type="duration",
                fiscal_year=period_end.year,
                fiscal_period="FY",
                form_type="10-K",
                accession_number=accession,
                available_at=available_at,
            )
        )
    return document


def test_research_panel_builds_reproducible_point_in_time_features(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    company = Company(ticker="TEST", cik="0000000001", name="Test Company")
    _add_document(
        company,
        accession="annual-2024",
        period_end=date(2024, 12, 31),
        available_at=datetime(2025, 2, 1, tzinfo=UTC),
        revenue=Decimal("100"),
        operating_income=Decimal("20"),
        passages=[
            "Legacy supplier concentration risk.",
            "Common competition disclosure.",
        ],
    )
    current = _add_document(
        company,
        accession="annual-2025",
        period_end=date(2025, 12, 31),
        available_at=datetime(2026, 2, 1, tzinfo=UTC),
        revenue=Decimal("120"),
        operating_income=Decimal("30"),
        passages=[
            "Common competition disclosure.",
            "Artificial intelligence regulation may increase compliance costs.",
        ],
    )
    _add_document(
        company,
        accession="annual-2026-future",
        period_end=date(2026, 12, 31),
        available_at=datetime(2027, 2, 1, tzinfo=UTC),
        revenue=Decimal("150"),
        operating_income=Decimal("35"),
        passages=["Future disclosure."],
    )

    with Session(engine) as session:
        session.add(company)
        session.commit()
        statements: list[str] = []
        event.listen(
            engine,
            "before_cursor_execute",
            lambda _conn, _cursor, statement, _params, _context, _many: statements.append(
                statement
            ),
        )
        panel = build_research_panel(
            session,
            ResearchPanelQuery(
                tickers=["TEST"],
                as_of=datetime(2026, 6, 1, tzinfo=UTC),
            ),
        )

    assert len(statements) == 4
    row = next(row for row in panel.rows if row.accession_number == current.accession_number)
    assert len(panel.rows) == 2
    assert row.revenue_growth == pytest.approx(0.2)
    assert row.operating_margin == pytest.approx(0.25)
    assert row.section_novelty["Risk Factors"] == pytest.approx(0.5)
    assert row.topic_mentions["ai"] == 1
    assert row.risk_added_passages == 1
    assert row.risk_removed_passages == 1
    assert row.max_source_available_at <= row.available_at
    assert row.source_accessions == ["annual-2025", "annual-2024"]
    assert panel.corpus_snapshot_id == row.corpus_snapshot_id

    output_dir = tmp_path
    json_path = write_research_panel(output_dir / "panel.json", panel, output_format="json")
    csv_path = write_research_panel(output_dir / "panel.csv", panel, output_format="csv")
    assert json.loads(json_path.read_text())[0]["ticker"] == "TEST"
    assert "corpus_snapshot_id" in csv_path.read_text().splitlines()[0]
    content, media_type = serialize_research_panel(panel, output_format="csv")
    assert media_type == "text/csv"
    assert b"corpus_snapshot_id" in content


def test_panel_leakage_validator_rejects_future_sources() -> None:
    available_at = datetime(2026, 2, 1, tzinfo=UTC)
    row = ResearchPanelRow(
        ticker="TEST",
        cik="0000000001",
        accession_number="annual-2025",
        form_type="10-K",
        period_end=date(2025, 12, 31),
        accepted_at=available_at,
        available_at=available_at,
        is_amendment=False,
        source_accessions=["annual-2025", "future-source"],
        feature_provenance={"filing_features": ["annual-2025"]},
        calculation_version="test",
        corpus_snapshot_id="snapshot",
        max_source_available_at=available_at + timedelta(days=1),
    )

    with pytest.raises(ValueError, match="Point-in-time leakage"):
        validate_point_in_time_rows([row])
