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
    FEATURE_VERSION,
    FeatureLineage,
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
        query = ResearchPanelQuery(
            tickers=["TEST"],
            as_of=datetime(2026, 6, 1, tzinfo=UTC),
        )
        panel = build_research_panel(session, query)
        repeated_panel = build_research_panel(session, query)

    assert len(statements) == 8
    row = next(row for row in panel.rows if row.accession_number == current.accession_number)
    repeated_row = next(
        row
        for row in repeated_panel.rows
        if row.accession_number == current.accession_number
    )
    assert len(panel.rows) == 2
    assert panel.feature_version == FEATURE_VERSION == "fdre-panel-v3"
    assert row.revenue_growth == pytest.approx(0.2)
    assert row.operating_margin == pytest.approx(0.25)
    assert row.section_novelty["Risk Factors"] == pytest.approx(0.5)
    assert row.topic_mentions["ai"] == 1
    assert row.risk_added_passages == 1
    assert row.risk_removed_passages == 1
    assert row.risk_current_passages == 2
    assert row.risk_previous_passages == 2
    assert row.risk_churn_rate == pytest.approx(0.5)
    assert row.max_source_available_at <= row.available_at
    assert row.source_accessions == ["annual-2025", "annual-2024"]
    assert panel.corpus_snapshot_id == row.corpus_snapshot_id
    assert "disclosure_similarity" not in row.feature_lineage

    filing_length = row.feature_lineage["filing_length"]
    assert filing_length.source_accessions == ["annual-2025"]
    assert filing_length.parameters == {"sections": []}
    assert filing_length.calculation_version == "filing-length-v1"

    novelty = row.feature_lineage["section_novelty"]
    assert novelty.source_accessions == ["annual-2025", "annual-2024"]
    assert novelty.max_source_available_at == row.available_at

    growth = row.feature_lineage["xbrl_growth"]
    assert growth.source_accessions == ["annual-2025", "annual-2024"]
    assert growth.calculation_version == "xbrl-growth-v1"

    margins = row.feature_lineage["xbrl_margins"]
    assert margins.source_accessions == ["annual-2025"]
    assert margins.calculation_version == "xbrl-margins-v1"

    assert {
        feature: lineage.lineage_id for feature, lineage in row.feature_lineage.items()
    } == {
        feature: lineage.lineage_id
        for feature, lineage in repeated_row.feature_lineage.items()
    }
    assert all(
        lineage.corpus_snapshot_id == panel.corpus_snapshot_id
        and lineage.max_source_available_at <= row.available_at
        for lineage in row.feature_lineage.values()
    )

    output_dir = tmp_path
    json_path = write_research_panel(output_dir / "panel.json", panel, output_format="json")
    csv_path = write_research_panel(output_dir / "panel.csv", panel, output_format="csv")
    exported = json.loads(json_path.read_text())
    assert exported[0]["ticker"] == "TEST"
    assert "feature_lineage" in exported[0]
    assert "corpus_snapshot_id" in csv_path.read_text().splitlines()[0]
    content, media_type = serialize_research_panel(panel, output_format="csv")
    assert media_type == "text/csv"
    assert b"feature_lineage" in content
    assert b"corpus_snapshot_id" in content



def test_research_panel_skips_storage_for_unselected_lightweight_features() -> None:
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
        passages=["Prior risk."],
    )
    _add_document(
        company,
        accession="annual-2025",
        period_end=date(2025, 12, 31),
        available_at=datetime(2026, 2, 1, tzinfo=UTC),
        revenue=Decimal("120"),
        operating_income=Decimal("30"),
        passages=["Current risk."],
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
                features=["filing_timing"],
            ),
        )

    assert len(statements) == 2
    assert panel.rows
    assert all(set(row.feature_lineage) == {"filing_timing"} for row in panel.rows)


def test_panel_snapshot_includes_filtered_comparable_source() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    company = Company(ticker="TEST", cik="0000000001", name="Test Company")
    prior = _add_document(
        company,
        accession="annual-2024",
        period_end=date(2024, 12, 31),
        available_at=datetime(2025, 2, 1, tzinfo=UTC),
        revenue=Decimal("100"),
        operating_income=Decimal("20"),
        passages=["Prior risk."],
    )
    prior.sha256_hash = "prior-v1"
    current = _add_document(
        company,
        accession="annual-2025",
        period_end=date(2025, 12, 31),
        available_at=datetime(2026, 2, 1, tzinfo=UTC),
        revenue=Decimal("120"),
        operating_income=Decimal("30"),
        passages=["Current risk."],
    )
    current.sha256_hash = "current-v1"

    query = ResearchPanelQuery(
        tickers=["TEST"],
        period_end_from=date(2025, 1, 1),
        as_of=datetime(2026, 6, 1, tzinfo=UTC),
    )
    with Session(engine) as session:
        session.add(company)
        session.commit()
        first = build_research_panel(session, query)
        assert [row.accession_number for row in first.rows] == ["annual-2025"]
        first_row = first.rows[0]
        assert first_row.feature_lineage["section_novelty"].source_accessions == [
            "annual-2025",
            "annual-2024",
        ]

        prior.sha256_hash = "prior-v2"
        session.commit()
        second = build_research_panel(session, query)

    assert second.corpus_snapshot_id != first.corpus_snapshot_id
    assert (
        second.rows[0].feature_lineage["section_novelty"].lineage_id
        != first_row.feature_lineage["section_novelty"].lineage_id
    )


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


def test_panel_leakage_validator_rejects_future_feature_source() -> None:
    available_at = datetime(2026, 2, 1, tzinfo=UTC)
    future_at = available_at + timedelta(seconds=1)
    row = ResearchPanelRow(
        ticker="TEST",
        cik="0000000001",
        accession_number="annual-2025",
        form_type="10-K",
        period_end=date(2025, 12, 31),
        accepted_at=available_at,
        available_at=available_at,
        is_amendment=False,
        source_accessions=["annual-2025"],
        feature_provenance={"filing_features": ["annual-2025"]},
        feature_lineage={
            "filing_length": FeatureLineage(
                feature="filing_length",
                calculation_version="filing-length-v1",
                parameters={"sections": []},
                source_accessions=["annual-2025"],
                source_available_at={"annual-2025": future_at},
                max_source_available_at=future_at,
                corpus_snapshot_id="snapshot",
                lineage_id="0" * 64,
            )
        },
        calculation_version="test",
        corpus_snapshot_id="snapshot",
        max_source_available_at=available_at,
    )

    with pytest.raises(ValueError, match="Point-in-time feature leakage"):
        validate_point_in_time_rows([row])


def test_latest_with_priors_only_preserves_materialized_row_semantics() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    company = Company(ticker="TEST", cik="0000000001", name="Test Company")
    for year, revenue, operating_income, passage in (
        (2023, "80", "12", "Legacy risk."),
        (2024, "100", "20", "Prior risk."),
        (2025, "120", "30", "Current risk."),
    ):
        _add_document(
            company,
            accession=f"annual-{year}",
            period_end=date(year, 12, 31),
            available_at=datetime(year + 1, 2, 1, tzinfo=UTC),
            revenue=Decimal(revenue),
            operating_income=Decimal(operating_income),
            passages=[passage],
        )

    query = ResearchPanelQuery(
        tickers=["TEST"],
        as_of=datetime(2026, 6, 1, tzinfo=UTC),
        features=["risk_changes", "xbrl_growth", "xbrl_margins"],
    )
    with Session(engine) as session:
        session.add(company)
        session.commit()
        full = build_research_panel(session, query)
        pruned = build_research_panel(
            session,
            query,
            latest_with_priors_only=True,
        )

    assert [row.accession_number for row in full.rows] == [
        "annual-2023",
        "annual-2024",
        "annual-2025",
    ]
    assert [row.accession_number for row in pruned.rows] == [
        "annual-2024",
        "annual-2025",
    ]
    assert pruned.corpus_snapshot_id == full.corpus_snapshot_id
    full_by_accession = {row.accession_number: row for row in full.rows}
    for row in pruned.rows:
        assert row.model_dump(mode="json") == full_by_accession[
            row.accession_number
        ].model_dump(mode="json")
    