from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.db import Base
from apps.api.app.models import ResearchExperiment
from fdre.research.event_study import EventStudyConfig, EventWindow, FilingEvent, MarketBar
from fdre.research.walk_forward import (
    WalkForwardConfig,
    WalkForwardMode,
    WalkForwardObservation,
    WalkForwardStudyReport,
    build_walk_forward_folds,
    generate_walk_forward_schedule,
    persist_walk_forward_study,
    run_walk_forward_signal_study,
)


def _observation(
    accession: str,
    event_session: date,
    window_end_session: date,
    *,
    feature: float = 0.5,
    outcome: float = 0.01,
) -> WalkForwardObservation:
    when = datetime.combine(event_session, datetime.min.time(), tzinfo=UTC)
    return WalkForwardObservation(
        ticker=accession.upper(),
        accession_number=accession,
        event_session=event_session,
        window="0:1",
        window_end_session=window_end_session,
        feature_value=feature,
        outcome_value=outcome,
        available_at=when,
        max_source_available_at=when,
    )


def _schedule_config(*, mode: WalkForwardMode = "expanding") -> WalkForwardConfig:
    return WalkForwardConfig(
        mode=mode,
        start_date=date(2018, 1, 1),
        end_date=date(2024, 1, 1),
        train_months=24,
        validation_months=12,
        test_months=12,
        step_months=12,
    )


def test_expanding_and_rolling_schedules_are_deterministic() -> None:
    sessions = [date(year, 6, 1) for year in range(2018, 2024)]

    expanding = generate_walk_forward_schedule(_schedule_config(), sessions)
    assert [
        (
            fold.train_start,
            fold.train_end,
            fold.validation_start,
            fold.validation_end,
            fold.test_start,
            fold.test_end,
        )
        for fold in expanding
    ] == [
        (
            date(2018, 1, 1),
            date(2020, 1, 1),
            date(2020, 1, 1),
            date(2021, 1, 1),
            date(2021, 1, 1),
            date(2022, 1, 1),
        ),
        (
            date(2018, 1, 1),
            date(2021, 1, 1),
            date(2021, 1, 1),
            date(2022, 1, 1),
            date(2022, 1, 1),
            date(2023, 1, 1),
        ),
        (
            date(2018, 1, 1),
            date(2022, 1, 1),
            date(2022, 1, 1),
            date(2023, 1, 1),
            date(2023, 1, 1),
            date(2024, 1, 1),
        ),
    ]

    rolling = generate_walk_forward_schedule(_schedule_config(mode="rolling"), sessions)
    assert rolling[1].train_start == date(2019, 1, 1)
    assert rolling[1].train_end == date(2021, 1, 1)
    assert rolling[1].test_start == date(2022, 1, 1)


def test_walk_forward_purges_unrealized_development_outcomes() -> None:
    config = WalkForwardConfig(
        start_date=date(2018, 1, 1),
        end_date=date(2022, 1, 1),
        train_months=24,
        validation_months=12,
        test_months=12,
        step_months=12,
    )
    observations = [
        _observation("train-known", date(2019, 6, 1), date(2019, 6, 3)),
        _observation("validation-known", date(2020, 3, 1), date(2020, 3, 3)),
        _observation("validation-crosses", date(2020, 12, 31), date(2021, 1, 1)),
        _observation("test", date(2021, 4, 1), date(2021, 4, 2)),
    ]

    folds, oos = build_walk_forward_folds(observations, config)

    assert len(folds) == 1
    fold = folds[0]
    assert fold.status == "eligible"
    assert fold.train_accessions == ["train-known"]
    assert fold.validation_accessions == ["validation-known"]
    assert fold.purged_development_accessions == ["validation-crosses"]
    assert fold.test_accessions == ["test"]
    assert not set(fold.train_accessions) & set(fold.validation_accessions)
    assert not set(fold.train_accessions) & set(fold.test_accessions)
    assert not set(fold.validation_accessions) & set(fold.test_accessions)
    assert [item.accession_number for item in oos] == ["test"]
    assert all(item.fold_id == fold.fold_id for item in oos)


def test_ineligible_fold_never_enters_sealed_oos_sample() -> None:
    config = WalkForwardConfig(
        start_date=date(2018, 1, 1),
        end_date=date(2022, 1, 1),
        train_months=24,
        validation_months=12,
        test_months=12,
        step_months=12,
        min_validation_events=2,
    )
    observations = [
        _observation("train", date(2019, 6, 1), date(2019, 6, 3)),
        _observation("validation", date(2020, 6, 1), date(2020, 6, 3)),
        _observation("test", date(2021, 6, 1), date(2021, 6, 3)),
    ]

    folds, oos = build_walk_forward_folds(observations, config)

    assert folds[0].status == "insufficient_data"
    assert folds[0].test_accessions == ["test"]
    assert folds[0].test_observation_count == 0
    assert "validation events 1 < minimum 2" in folds[0].eligibility_reasons
    assert oos == []


def _synthetic_events_and_bars() -> tuple[list[FilingEvent], list[MarketBar]]:
    events: list[FilingEvent] = []
    bars: list[MarketBar] = []
    benchmark_dates: set[date] = set()
    for index, year in enumerate(range(2018, 2024), start=1):
        ticker = f"T{index:02d}"
        start = date(year, 6, 1)
        end = date(year, 6, 2)
        benchmark_dates.update({start, end})
        when = datetime(year, 6, 1, 9, 0, tzinfo=UTC)
        events.append(
            FilingEvent(
                ticker=ticker,
                accession_number=f"acc-{year}",
                available_at=when,
                max_source_available_at=when,
                feature_value=float(index),
            )
        )
        bars.extend(
            [
                MarketBar(ticker=ticker, date=start, adjusted_close=100.0),
                MarketBar(ticker=ticker, date=end, adjusted_close=100.0 + index),
            ]
        )
    bars.extend(
        MarketBar(ticker="SPY", date=day, adjusted_close=100.0)
        for day in sorted(benchmark_dates)
    )
    return events, bars


def _run_synthetic(
    events: list[FilingEvent],
    bars: list[MarketBar],
) -> WalkForwardStudyReport:
    return run_walk_forward_signal_study(
        events,
        bars,
        EventStudyConfig(
            windows=[EventWindow(start=0, end=1)],
            bootstrap_iterations=100,
        ),
        _schedule_config(),
        signal_name="risk_factor_churn",
        dataset_version="panel-v1",
        feature_version="risk-churn-v1",
        code_sha="a" * 40,
        definition={"feature": "risk_churn_rate", "direction": "higher"},
    )


def test_walk_forward_runner_emits_only_sealed_oos_and_stable_identity() -> None:
    events, bars = _synthetic_events_and_bars()

    first = _run_synthetic(events, bars)
    second = _run_synthetic(events, list(reversed(bars)))

    assert first.sealed_oos is True
    assert first.selection_policy == "precommitted_signal_definition"
    assert first.fold_count == 3
    assert first.eligible_fold_count == 3
    assert first.oos_event_count == 3
    assert first.oos_observation_count == 3
    assert [item.accession_number for item in first.oos_observations] == [
        "acc-2021",
        "acc-2022",
        "acc-2023",
    ]
    assert all(item.available_at.tzinfo is not None for item in first.oos_observations)
    assert len(first.market_data_version) == 64
    assert len(first.universe_snapshot_id) == 64
    assert len(first.feature_snapshot_id) == 64
    assert first.experiment_key == second.experiment_key
    assert first.market_data_version == second.market_data_version

    changed_bars = list(bars)
    target = next(
        index
        for index, bar in enumerate(changed_bars)
        if bar.ticker == "T06" and bar.date == date(2023, 6, 2)
    )
    changed_bars[target] = changed_bars[target].model_copy(
        update={"adjusted_close": changed_bars[target].adjusted_close + 1.0}
    )
    changed_market = _run_synthetic(events, changed_bars)
    assert changed_market.market_data_version != first.market_data_version
    assert changed_market.experiment_key != first.experiment_key


def test_feature_snapshot_is_separate_from_universe_membership() -> None:
    events, bars = _synthetic_events_and_bars()
    first = _run_synthetic(events, bars)
    changed_events = list(events)
    changed_events[0] = changed_events[0].model_copy(update={"feature_value": 999.0})
    changed = _run_synthetic(changed_events, bars)

    assert changed.universe_snapshot_id == first.universe_snapshot_id
    assert changed.feature_snapshot_id != first.feature_snapshot_id
    assert changed.experiment_key != first.experiment_key


def test_walk_forward_persistence_is_idempotent() -> None:
    events, bars = _synthetic_events_and_bars()
    report = _run_synthetic(events, bars)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = persist_walk_forward_study(session, report)
        second = persist_walk_forward_study(session, report)
        count = session.scalar(select(func.count()).select_from(ResearchExperiment))

    assert first.id == second.id
    assert count == 1
    assert first.experiment_type == "walk_forward_signal_study"


def test_walk_forward_rejects_overlapping_test_folds() -> None:
    with pytest.raises(ValueError, match="test folds do not overlap"):
        WalkForwardConfig(test_months=12, step_months=6)
