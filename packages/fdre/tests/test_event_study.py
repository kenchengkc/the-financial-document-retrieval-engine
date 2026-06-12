from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import ResearchExperiment
from fdre.research.event_study import (
    EventStudyConfig,
    EventWindow,
    FilingEvent,
    MarketBar,
    load_market_bars,
    persist_event_study,
    run_event_study,
    validate_event_inputs,
)


def _bars(ticker: str, closes: list[float]) -> list[MarketBar]:
    dates = [
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
    ]
    return [
        MarketBar(ticker=ticker, date=bar_date, adjusted_close=close)
        for bar_date, close in zip(dates, closes, strict=True)
    ]


def test_event_study_aligns_sessions_bootstraps_and_persists() -> None:
    before_close = FilingEvent(
        ticker="AAA",
        accession_number="before-close",
        available_at=datetime(2026, 1, 5, 20, tzinfo=UTC),
        max_source_available_at=datetime(2026, 1, 5, 20, tzinfo=UTC),
    )
    after_close = FilingEvent(
        ticker="AAA",
        accession_number="after-close",
        available_at=datetime(2026, 1, 5, 22, tzinfo=UTC),
        max_source_available_at=datetime(2026, 1, 5, 22, tzinfo=UTC),
    )
    config = EventStudyConfig(
        benchmark_ticker="SPY",
        windows=[EventWindow(start=0, end=1)],
        bootstrap_iterations=200,
        random_seed=7,
        walk_forward_splits=[date(2026, 1, 6)],
    )
    report = run_event_study(
        [before_close, after_close],
        [
            *_bars("AAA", [100, 110, 121, 133.1]),
            *_bars("SPY", [100, 101, 102, 103]),
        ],
        config,
        dataset_version="bars-v1",
        feature_version="fdre-panel-v1",
        code_sha="abc123",
    )

    sessions = {
        observation.accession_number: observation.event_session
        for observation in report.observations
    }
    assert sessions == {
        "before-close": date(2026, 1, 5),
        "after-close": date(2026, 1, 6),
    }
    assert report.results[0].sample_size == 2
    assert report.results[0].mean_abnormal_return is not None
    assert report.results[0].confidence_interval_low is not None
    assert report.results[0].adjusted_p_value is not None
    assert report.walk_forward[0].train_event_count == 1
    assert report.walk_forward[0].test_event_count == 1

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = persist_event_study(session, report)
        second = persist_event_study(session, report)
        count = session.scalar(select(func.count()).select_from(ResearchExperiment))

    assert first.id == second.id
    assert count == 1


def test_market_bar_csv_loader_and_leakage_guard(tmp_path: Path) -> None:
    path = tmp_path / "bars.csv"
    path.write_text(
        "ticker,date,adjusted_close\n"
        "AAA,2026-01-02,100\n"
        "SPY,2026-01-02,100\n"
    )
    bars = load_market_bars(path)
    assert bars[0] == MarketBar(
        ticker="AAA",
        date=date(2026, 1, 2),
        adjusted_close=100,
    )

    available_at = datetime(2026, 1, 5, tzinfo=UTC)
    leaking = FilingEvent(
        ticker="AAA",
        accession_number="leaking",
        available_at=available_at,
        max_source_available_at=available_at + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="Feature leakage"):
        validate_event_inputs([leaking])
