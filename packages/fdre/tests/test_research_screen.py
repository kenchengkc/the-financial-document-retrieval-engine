from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement, FinancialFact
from fdre.research.screen import (
    ResearchScreenPlan,
    ScreenCondition,
    execute_research_screen,
)
from fdre.retrieval.query import RetrievalCandidate, SearchFilters


def _add_quarter(
    company: Company,
    *,
    accession: str,
    period_end: date,
    available_at: datetime,
    revenue: str,
    capex: str,
    text: str,
) -> tuple[Document, Chunk]:
    document = Document(
        company=company,
        source_type="sec",
        form_type="10-Q",
        filing_date=available_at.date(),
        period_end_date=period_end,
        accepted_at=available_at,
        available_at=available_at,
        accession_number=accession,
    )
    element = DocumentElement(
        document=document,
        element_type="text",
        section="MD&A",
        text=text,
        reading_order=1,
    )
    chunk = Chunk(
        document=document,
        element=element,
        chunk_text=text,
        chunk_type="text",
        section="MD&A",
        token_count=len(text.split()),
        metadata_json={"ticker": company.ticker, "form_type": "10-Q"},
    )
    document.chunks.append(chunk)
    for metric, concept, value in (
        ("revenue", "Revenues", revenue),
        ("capex", "PaymentsToAcquirePropertyPlantAndEquipment", capex),
    ):
        company.financial_facts.append(
            FinancialFact(
                document=document,
                ticker=company.ticker,
                fact_key=f"{accession}-{metric}",
                taxonomy="us-gaap",
                concept=concept,
                canonical_metric=metric,
                value=Decimal(value),
                unit="USD",
                period_start=date(period_end.year, 1, 1),
                period_end=period_end,
                period_type="duration",
                fiscal_year=period_end.year,
                fiscal_period="Q1",
                form_type="10-Q",
                accession_number=accession,
                available_at=available_at,
            )
        )
    return document, chunk


def _seed_screen_data(session: Session) -> dict[str, Chunk]:
    alpha = Company(ticker="AAA", cik="0000000001", name="Alpha")
    _, alpha_prior = _add_quarter(
        alpha,
        accession="aaa-2024-q1",
        period_end=date(2024, 3, 31),
        available_at=datetime(2024, 5, 1, tzinfo=UTC),
        revenue="100",
        capex="10",
        text="Prior AI infrastructure disclosure.",
    )
    _, alpha_current = _add_quarter(
        alpha,
        accession="aaa-2025-q1",
        period_end=date(2025, 3, 31),
        available_at=datetime(2025, 5, 1, tzinfo=UTC),
        revenue="120",
        capex="24",
        text="AI data center capital investment increased materially.",
    )
    _add_quarter(
        alpha,
        accession="aaa-2026-q1-future",
        period_end=date(2026, 3, 31),
        available_at=datetime(2027, 5, 1, tzinfo=UTC),
        revenue="130",
        capex="13",
        text="Future disclosure that must not leak.",
    )

    beta = Company(ticker="BBB", cik="0000000002", name="Beta")
    _add_quarter(
        beta,
        accession="bbb-2024-q1",
        period_end=date(2024, 3, 31),
        available_at=datetime(2024, 5, 2, tzinfo=UTC),
        revenue="100",
        capex="20",
        text="Prior infrastructure disclosure.",
    )
    _, beta_current = _add_quarter(
        beta,
        accession="bbb-2025-q1",
        period_end=date(2025, 3, 31),
        available_at=datetime(2025, 5, 2, tzinfo=UTC),
        revenue="120",
        capex="18",
        text="Current infrastructure disclosure.",
    )
    session.add_all([alpha, beta])
    session.commit()
    return {
        "alpha_prior": alpha_prior,
        "alpha_current": alpha_current,
        "beta_current": beta_current,
    }


def test_screen_filters_structured_features_before_one_semantic_search() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        chunks = _seed_screen_data(session)
        calls: list[tuple[str, SearchFilters, int]] = []

        def semantic_search(
            query: str,
            filters: SearchFilters,
            top_k: int,
        ) -> list[RetrievalCandidate]:
            calls.append((query, filters, top_k))
            return [
                RetrievalCandidate(
                    chunk_id=chunks["alpha_prior"].id,
                    text=chunks["alpha_prior"].chunk_text,
                    metadata={"ticker": "AAA"},
                    rerank_score=0.99,
                ),
                RetrievalCandidate(
                    chunk_id=chunks["alpha_current"].id,
                    text=chunks["alpha_current"].chunk_text,
                    metadata={"ticker": "AAA"},
                    rerank_score=0.80,
                ),
                RetrievalCandidate(
                    chunk_id=chunks["beta_current"].id,
                    text=chunks["beta_current"].chunk_text,
                    metadata={"ticker": "BBB"},
                    rerank_score=0.95,
                ),
            ]

        result = execute_research_screen(
            session,
            ResearchScreenPlan(
                as_of=datetime(2026, 6, 1, tzinfo=UTC),
                conditions=[
                    ScreenCondition(
                        metric="capex_to_revenue",
                        operator="gt",
                        value=0,
                        change_from_prior=True,
                    )
                ],
                semantic_query="AI-related capital expenditure",
                semantic_candidate_limit=50,
                evidence_per_issuer=2,
            ),
            semantic_search=semantic_search,
        )

    assert len(calls) == 1
    query, filters, top_k = calls[0]
    assert query == "AI-related capital expenditure"
    assert filters.tickers == ["AAA"]
    assert filters.as_of == datetime(2026, 6, 1, tzinfo=UTC)
    assert top_k == 50

    assert result.manifest.universe_count == 2
    assert result.manifest.structured_match_count == 1
    assert result.manifest.semantic_search_calls == 1
    assert result.manifest.semantic_candidate_count == 3
    assert result.manifest.matched_count == 1
    assert result.manifest.max_information_timestamp is not None
    assert result.manifest.max_information_timestamp <= result.plan.as_of

    assert [row.ticker for row in result.rows] == ["AAA"]
    row = result.rows[0]
    assert row.accession_number == "aaa-2025-q1"
    assert row.prior_accession_number == "aaa-2024-q1"
    assert row.semantic_score == pytest.approx(0.80)
    assert [candidate.chunk_id for candidate in row.evidence] == [
        chunks["alpha_current"].id
    ]
    assert row.conditions[0].current_value == pytest.approx(0.20)
    assert row.conditions[0].prior_value == pytest.approx(0.10)
    assert row.conditions[0].observed_value == pytest.approx(0.10)
    assert row.conditions[0].passed is True
    assert "aaa-2026-q1-future" not in row.source_accessions


def test_structured_only_screen_makes_no_semantic_call() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_screen_data(session)
        result = execute_research_screen(
            session,
            ResearchScreenPlan(
                as_of=datetime(2026, 6, 1, tzinfo=UTC),
                conditions=[
                    ScreenCondition(
                        metric="capex_to_revenue",
                        operator="gt",
                        value=0.16,
                    )
                ],
                rank_by="capex_to_revenue",
            ),
        )

    assert result.manifest.semantic_search_calls == 0
    assert result.manifest.semantic_candidate_count == 0
    assert [row.ticker for row in result.rows] == ["AAA"]
    assert result.rows[0].rank_value == pytest.approx(0.20)


def test_screen_plan_requires_timezone_and_semantic_source_for_semantic_rank() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        ResearchScreenPlan(as_of=datetime(2026, 6, 1), semantic_query="AI")

    with pytest.raises(ValidationError, match="semantic_query"):
        ResearchScreenPlan(
            as_of=datetime(2026, 6, 1, tzinfo=UTC),
            rank_by="semantic_score",
        )
