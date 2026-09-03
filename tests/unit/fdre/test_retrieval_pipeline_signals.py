from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from scripts.pipelines.retrieval_pipeline import (
    _fundamental_metric,
    _is_annual_comparative_fact,
    _neutralize_signal_events,
    _panel_signal_events,
    _signal_feature_value,
    _signal_panel_features,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.db import Base
from apps.api.app.models import Company
from fdre.research.event_study import FilingEvent


def test_filing_lateness_is_a_standalone_panel_signal() -> None:
    row = SimpleNamespace(filing_delay_days=47)

    assert _signal_panel_features("filing_lateness") == ["filing_timing"]
    assert _signal_feature_value(row, "filing_lateness") == 47.0


def test_filing_lateness_rejects_missing_delay() -> None:
    row = SimpleNamespace(filing_delay_days=None)

    assert _signal_feature_value(row, "filing_lateness") is None


def test_risk_churn_uses_normalized_two_sided_change() -> None:
    row = SimpleNamespace(risk_churn_rate=0.35)

    assert _signal_panel_features("risk_factor_churn") == ["risk_changes"]
    assert _signal_feature_value(row, "risk_factor_churn") == pytest.approx(0.35)


def test_filing_delay_surprise_uses_prior_issuer_form_history() -> None:
    rows = [
        _panel_row("a", 40, datetime(2023, 2, 1, tzinfo=UTC)),
        _panel_row("b", 42, datetime(2024, 2, 1, tzinfo=UTC)),
        _panel_row("c", 47, datetime(2025, 2, 1, tzinfo=UTC)),
    ]

    events = _panel_signal_events(
        rows,
        signal_name="filing_delay_surprise",
        outcome_name="realized_volatility",
    )

    assert events[0].feature_value is None
    assert events[1].feature_value is None
    assert events[2].feature_value == pytest.approx(6.0)


def test_fundamental_scores_are_oriented_higher_is_better() -> None:
    current = date(2025, 12, 31)
    prior = date(2024, 12, 31)
    values = {
        "NetIncomeLoss": [(current, 10.0), (prior, 9.0)],
        "NetCashProvidedByUsedInOperatingActivities": [
            (current, 15.0),
            (prior, 11.0),
        ],
        "Assets": [(current, 100.0), (prior, 80.0)],
        "OperatingIncomeLoss": [(current, 20.0), (prior, 15.0)],
        "Revenues": [(current, 100.0), (prior, 100.0)],
        "CommonStockSharesOutstanding": [(current, 90.0), (prior, 100.0)],
    }

    assert _fundamental_metric("earnings_quality", values) == pytest.approx(5 / 90)
    assert _fundamental_metric("operating_profitability", values) == pytest.approx(20 / 90)
    assert _fundamental_metric("operating_margin_momentum", values) == pytest.approx(0.05)
    assert _fundamental_metric("asset_growth", values) == pytest.approx(-0.25)
    assert _fundamental_metric("net_share_issuance", values) == pytest.approx(0.10)


def test_fundamental_fact_filter_rejects_quarterly_contexts() -> None:
    period_end = date(2025, 12, 31)

    assert _is_annual_comparative_fact(
        "OperatingIncomeLoss", date(2025, 1, 1), period_end
    )
    assert not _is_annual_comparative_fact(
        "OperatingIncomeLoss", date(2025, 10, 1), period_end
    )
    assert _is_annual_comparative_fact("Assets", None, period_end)
    assert not _is_annual_comparative_fact(
        "Assets", date(2025, 1, 1), period_end
    )


def test_sector_neutralization_materializes_sqlalchemy_rows() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    when = datetime(2025, 2, 1, tzinfo=UTC)
    tickers = ["A", "B", "C", "D"]
    with Session(engine) as session:
        session.add_all(
            Company(ticker=ticker, cik=str(index), name=ticker, sector="Technology")
            for index, ticker in enumerate(tickers, start=1)
        )
        session.commit()
        events = [
            FilingEvent(
                ticker=ticker,
                accession_number=f"acc-{ticker}",
                available_at=when,
                max_source_available_at=when,
                feature_value=float(index),
            )
            for index, ticker in enumerate(tickers, start=1)
        ]

        neutralized, label = _neutralize_signal_events(
            session,
            events,
            signal_name="disclosure_similarity",
            mode="sector",
        )

    assert label == "period+sector"
    assert all(event.feature_value is not None for event in neutralized)
    assert sum(event.feature_value or 0 for event in neutralized) == pytest.approx(0)


def _panel_row(accession: str, delay: int, available_at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        ticker="TEST",
        form_type="10-K",
        accession_number=accession,
        filing_delay_days=delay,
        available_at=available_at,
        max_source_available_at=available_at,
    )
