from __future__ import annotations

from datetime import UTC, date, datetime

from fdre.research.event_study import EventStudyConfig, EventWindow, FilingEvent, MarketBar
from fdre.research.signal_study import run_signal_study

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
    assert window.information_coefficient is not None and window.information_coefficient > 0.95
    means = [
        q.mean_abnormal_return
        for q in window.quantiles
        if q.mean_abnormal_return is not None
    ]
    assert len(means) == len(window.quantiles)
    assert means == sorted(means)  # quantile returns increase with the signal
    assert window.long_short_mean is not None and window.long_short_mean > 0
    assert window.long_short_p_value is not None and window.long_short_p_value < 0.05


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
