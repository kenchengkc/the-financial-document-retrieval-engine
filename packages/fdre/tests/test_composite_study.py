from __future__ import annotations

from datetime import UTC, date, datetime

from fdre.research.composite_study import (
    CompositeEvent,
    SignalComponent,
    run_composite_study,
    standardize_by_period,
)
from fdre.research.event_study import EventStudyConfig, EventWindow, MarketBar
from fdre.research.sectors import sic_to_sector

DATES = [date(2024, 1, day) for day in range(2, 9)]


def _benchmark() -> list[MarketBar]:
    return [MarketBar(ticker="SPY", date=day, adjusted_close=100.0) for day in DATES]


def test_composite_recovers_real_signal_and_flags_correlations() -> None:
    # signal_a drives the forward return; signal_b is noise. The composite IC
    # should be positive, signal_a's component IC should dominate signal_b's,
    # and the engine should report their (near-zero) correlation.
    events: list[CompositeEvent] = []
    bars: list[MarketBar] = _benchmark()
    n = 40
    when = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
    for index in range(n):
        a = (index + 1) / (n + 1)
        b = ((index * 7) % n + 1) / (n + 1)  # decorrelated from a
        forward = 0.10 * (a - 0.5)  # benchmark flat -> abnormal == forward
        ticker = f"T{index:02d}"
        end_price = 100.0 * (1 + forward)
        prices = [100.0, end_price] + [end_price] * (len(DATES) - 2)
        bars.extend(
            MarketBar(ticker=ticker, date=day, adjusted_close=price)
            for day, price in zip(DATES, prices, strict=False)
        )
        events.append(
            CompositeEvent(
                ticker=ticker,
                accession_number=f"acc-{index:04d}",
                available_at_period="2024Q1",
                available_at=when,
                max_source_available_at=when,
                raw={"signal_a": a, "signal_b": b},
            )
        )

    report = run_composite_study(
        events,
        [SignalComponent(name="signal_a", sign=1), SignalComponent(name="signal_b", sign=1)],
        bars,
        EventStudyConfig(windows=[EventWindow(start=0, end=1)], bootstrap_iterations=300),
        n_quantiles=5,
        dataset_version="test",
        feature_version="test",
        code_sha="test",
    )

    assert report.signal_name == "composite"
    assert report.component_signals == ["signal_a", "signal_b"]
    by_signal = {
        c.signal: c.information_coefficient for c in report.components if c.window == "0:1"
    }
    assert by_signal["signal_a"] is not None and by_signal["signal_a"] > 0.9
    assert by_signal["signal_b"] is not None and abs(by_signal["signal_b"]) < by_signal["signal_a"]
    assert by_signal["composite"] is not None and by_signal["composite"] > 0
    assert len(report.signal_correlations) == 1
    assert report.signal_correlations[0].correlation is not None
    assert report.neutralization == "period"


def test_sic_to_sector_maps_known_codes() -> None:
    assert sic_to_sector(3571) == "Information Technology"  # electronic computers
    assert sic_to_sector(2834) == "Health Care"  # pharmaceutical preparations
    assert sic_to_sector(1311) == "Energy"  # crude petroleum & natural gas
    assert sic_to_sector(6022) == "Financials"  # state commercial banks
    assert sic_to_sector(4911) == "Utilities"  # electric services
    assert sic_to_sector(None) == "Unknown"
    assert sic_to_sector("not-a-code") == "Unknown"


def test_sector_neutralization_demeans_within_sector() -> None:
    # Two sectors with very different signal levels in one period. Sector
    # neutralization should remove the sector mean so the per-sector cross-section
    # is centred, rather than the high-level sector dominating the ranking.
    components = [SignalComponent(name="sig", sign=1)]
    sectors = {}
    events: list[CompositeEvent] = []
    when = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)
    # Sector A levels ~ {10, 12, 14, 16}; Sector B levels ~ {100, 102, 104, 106}.
    for index, level in enumerate([10.0, 12.0, 14.0, 16.0, 100.0, 102.0, 104.0, 106.0]):
        accession = f"acc-{index}"
        sector = "A" if index < 4 else "B"
        sectors[accession] = sector
        events.append(
            CompositeEvent(
                ticker=f"T{index}",
                accession_number=accession,
                available_at_period="2024Q1",
                available_at=when,
                max_source_available_at=when,
                raw={"sig": level},
            )
        )

    period_z = standardize_by_period(events, components)
    sector_z = standardize_by_period(events, components, sector_by_accession=sectors, min_group=4)

    # Period-only: sector B (high level) sits entirely above sector A.
    assert period_z["acc-0"]["sig"] < 0 < period_z["acc-4"]["sig"]
    # Sector-neutral: each sector is centred on its own mean, so the lowest member
    # of each sector gets the same negative z-score.
    assert sector_z["acc-0"]["sig"] == sector_z["acc-4"]["sig"]
    assert sector_z["acc-0"]["sig"] < 0
