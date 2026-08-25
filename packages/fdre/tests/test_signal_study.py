from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from fdre.research.event_study import EventStudyConfig, EventWindow, FilingEvent, MarketBar
from fdre.research.panel import FeatureLineage
from fdre.research.signal_study import (
    run_realized_volatility_signal_study,
    run_signal_study,
)

DATES = [date(2024, 1, day) for day in range(2, 9)]


def _benchmark() -> list[MarketBar]:
    return [MarketBar(ticker="SPY", date=day, adjusted_close=100.0) for day in DATES]


def _event(
    index: int, feature: float, forward_return: float
) -> tuple[FilingEvent, list[MarketBar]]:
    ticker = f"T{index:02d}"
    end_price = 100.0 * (1 + forward_return)
    prices = [100.0, end_price] + [end_price] * (len(DATES) - 2)
    bars = [
        MarketBar(ticker=ticker, date=day, adjusted_close=price)
        for day, price in zip(DATES, prices, strict=False)
    ]
    when = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)  # before US close -> session 0
    event = FilingEvent(
        ticker=ticker,
        accession_number=f"acc-{index:04d}",
        available_at=when,
        max_source_available_at=when,
        feature_value=feature,
    )
    return event, bars


def _with_disclosure_lineage(
    event: FilingEvent,
    *,
    lineage_id: str | None = None,
) -> FilingEvent:
    lineage = FeatureLineage(
        feature="disclosure_similarity",
        calculation_version="disclosure-similarity-v1",
        source_accessions=[event.accession_number],
        source_available_at={event.accession_number: event.available_at},
        max_source_available_at=event.available_at,
        corpus_snapshot_id="snapshot-v1",
        lineage_id=lineage_id
        or hashlib.sha256(event.accession_number.encode("utf-8")).hexdigest(),
    )
    return event.model_copy(update={"feature_lineage": lineage})


def test_signal_study_recovers_a_monotonic_signal() -> None:
    # forward abnormal return is monotone increasing in the feature: the engine
    # should report a strong positive IC, monotone quantile returns, and a
    # significant positive long-short spread.
    events: list[FilingEvent] = []
    bars: list[MarketBar] = _benchmark()
    n = 40
    for index in range(n):
        feature = (index + 1) / (n + 1)
        forward_return = 0.10 * (feature - 0.5)  # benchmark is flat -> abnormal == forward_return
        event, ticker_bars = _event(index, feature, forward_return)
        events.append(event)
        bars.extend(ticker_bars)

    config = EventStudyConfig(windows=[EventWindow(start=0, end=1)], bootstrap_iterations=500)
    report = run_signal_study(
        events,
        bars,
        config,
        signal_name="disclosure_similarity",
        n_quantiles=5,
        dataset_version="test",
        feature_version="test",
        code_sha="test",
    )

    assert report.event_count == n
    window = report.results[0]
    assert window.sample_size == n
    assert window.cluster_count == n
    assert report.bootstrap_unit == "issuer"
    assert window.information_coefficient is not None and window.information_coefficient > 0.95
    means = [
        q.mean_abnormal_return
        for q in window.quantiles
        if q.mean_abnormal_return is not None
    ]
    assert len(means) == len(window.quantiles)
    assert means == sorted(means)  # quantile returns increase with the signal
    assert window.long_short_mean is not None and window.long_short_mean > 0
    assert window.long_short_p_value is not None
    assert 0 < window.long_short_p_value < 0.05
    assert len(report.period_results) == 1
    assert report.period_results[0].period == "2024"
    assert report.period_results[0].information_coefficient is not None
    assert report.period_results[0].information_coefficient > 0.95
    assert report.feature_lineage_complete is False
    assert report.feature_lineage_digest is None
    assert report.feature_lineage_by_accession == {}


def test_signal_study_handles_thin_samples() -> None:
    event, bars = _event(0, 0.4, 0.01)
    config = EventStudyConfig(windows=[EventWindow(start=0, end=1)])
    report = run_signal_study(
        [event],
        bars + _benchmark(),
        config,
        signal_name="disclosure_similarity",
        n_quantiles=5,
        dataset_version="test",
        feature_version="test",
        code_sha="test",
    )
    window = report.results[0]
    assert window.information_coefficient is None
    assert window.quantiles == []
    assert window.long_short_mean is None


def test_realized_volatility_signal_study_recovers_monotonic_risk() -> None:
    events: list[FilingEvent] = []
    bars: list[MarketBar] = _benchmark()
    n = 30
    for index in range(n):
        feature = (index + 1) / n
        daily_return = 0.002 + feature * 0.01
        prices = [100.0]
        for _ in range(len(DATES) - 1):
            prices.append(prices[-1] * (1 + daily_return))
        ticker = f"V{index:02d}"
        bars.extend(
            MarketBar(ticker=ticker, date=day, adjusted_close=price)
            for day, price in zip(DATES, prices, strict=False)
        )
        when = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
        events.append(
            FilingEvent(
                ticker=ticker,
                accession_number=f"vol-{index:04d}",
                available_at=when,
                max_source_available_at=when,
                feature_value=feature,
            )
        )

    config = EventStudyConfig(windows=[EventWindow(start=0, end=3)], bootstrap_iterations=500)
    report = run_realized_volatility_signal_study(
        events,
        bars,
        config,
        signal_name="risk_factor_expansion",
        n_quantiles=5,
        dataset_version="test",
        feature_version="test",
        code_sha="test",
    )

    assert report.outcome_name == "realized_volatility"
    assert report.event_count == n
    window = report.results[0]
    assert window.information_coefficient is not None and window.information_coefficient > 0.95
    means = [
        q.mean_abnormal_return
        for q in window.quantiles
        if q.mean_abnormal_return is not None
    ]
    assert means == sorted(means)
    assert window.long_short_mean is not None and window.long_short_mean > 0


def test_signal_study_fingerprints_complete_feature_lineage() -> None:
    events: list[FilingEvent] = []
    bars: list[MarketBar] = _benchmark()
    n = 10
    for index in range(n):
        feature = (index + 1) / (n + 1)
        event, ticker_bars = _event(index, feature, 0.05 * (feature - 0.5))
        events.append(_with_disclosure_lineage(event))
        bars.extend(ticker_bars)

    config = EventStudyConfig(windows=[EventWindow(start=0, end=1)], bootstrap_iterations=100)
    first = run_signal_study(
        events,
        bars,
        config,
        signal_name="disclosure_similarity",
        n_quantiles=5,
        dataset_version="same-dataset",
        feature_version="fdre-panel-v3",
        code_sha="same-code",
    )

    assert first.feature_lineage_complete is True
    assert len(first.feature_lineage_by_accession) == n
    assert first.feature_lineage_digest is not None
    assert len(first.feature_lineage_digest) == 64

    changed_events = list(events)
    changed_events[0] = _with_disclosure_lineage(
        changed_events[0],
        lineage_id="f" * 64,
    )
    second = run_signal_study(
        changed_events,
        bars,
        config,
        signal_name="disclosure_similarity",
        n_quantiles=5,
        dataset_version="same-dataset",
        feature_version="fdre-panel-v3",
        code_sha="same-code",
    )

    assert second.feature_lineage_digest != first.feature_lineage_digest
    assert second.experiment_key != first.experiment_key


def test_signal_study_marks_partial_lineage_without_claiming_complete_digest() -> None:
    first_event, first_bars = _event(0, 0.2, -0.01)
    second_event, second_bars = _event(1, 0.8, 0.01)
    first_event = _with_disclosure_lineage(first_event)
    config = EventStudyConfig(windows=[EventWindow(start=0, end=1)], bootstrap_iterations=100)

    report = run_signal_study(
        [first_event, second_event],
        [*_benchmark(), *first_bars, *second_bars],
        config,
        signal_name="disclosure_similarity",
        n_quantiles=1,
        dataset_version="test",
        feature_version="fdre-panel-v3",
        code_sha="test",
    )

    assert report.feature_lineage_complete is False
    assert report.feature_lineage_digest is None
    assert first_event.feature_lineage is not None
    assert report.feature_lineage_by_accession == {
        first_event.accession_number: first_event.feature_lineage.lineage_id
    }
