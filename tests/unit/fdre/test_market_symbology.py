from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fdre.research import market_data, market_symbology
from fdre.research.event_study import EventStudyConfig, EventWindow, FilingEvent, MarketBar
from fdre.research.hu5_multiclass import HU5EventOutcomeMapping, HU5OutcomeComponent


def _component(symbol: str) -> HU5OutcomeComponent:
    return HU5OutcomeComponent(
        security_id=1,
        symbol=symbol,
        membership_source_hash="membership",
        identity_source_hash="identity",
    )


def _mapping(accession: str, symbol: str) -> HU5EventOutcomeMapping:
    return HU5EventOutcomeMapping(
        accession_number=accession,
        as_of="2012-02-27",
        snapshot_id="snapshot",
        cik="0001103982",
        observation_ticker=symbol,
        components=(_component(symbol),),
    )


def _event(accession: str, symbol: str, day: date) -> FilingEvent:
    available = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
    return FilingEvent(
        ticker=symbol,
        accession_number=accession,
        available_at=available,
        max_source_available_at=available,
        feature_value=1.0,
    )


def _weekday_bars(symbol: str, start: date, end: date) -> list[MarketBar]:
    bars: list[MarketBar] = []
    cursor = start
    price = 100.0
    while cursor <= end:
        if cursor.weekday() < 5:
            bars.append(MarketBar(ticker=symbol, date=cursor, adjusted_close=price))
            price += 0.1
        cursor += timedelta(days=1)
    return bars


def test_frozen_market_symbology_manifest_matches_precommitment() -> None:
    assert (
        market_symbology.computed_hu5_market_symbology_manifest_id()
        == market_symbology.HU5_MARKET_SYMBOLOGY_MANIFEST_ID
        == "89c67316e1417682519996ea2d387a44802b2eb63c225f22cf87aca29db6c328"
    )


def test_provider_aliases_are_exact_and_unrelated_symbols_are_identity() -> None:
    assert {
        item.historical_symbol: item.provider_symbol
        for item in market_symbology.HU5_MARKET_SYMBOL_ALIASES
    } == {
        "BLL": "BALL",
        "KFT": "MDLZ",
        "MHFI": "SPGI",
        "MHP": "SPGI",
        "MMC": "MRSH",
        "PKI": "RVTY",
        "TMK": "GL",
    }
    assert market_symbology.hu5_provider_symbol("mhp") == "SPGI"
    assert market_symbology.hu5_provider_symbol("AAPL") == "AAPL"


def test_hu5_fetch_relabels_one_provider_history_to_historical_symbols(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def fake_fetch_market_bars(
        tickers: list[str],
        start: date,
        end: date,
        **kwargs: Any,
    ) -> tuple[list[MarketBar], list[str]]:
        captured["tickers"] = tickers
        captured["benchmark"] = kwargs["benchmark"]
        return (
            [
                MarketBar(ticker="SPGI", date=date(2012, 1, 17), adjusted_close=10.0),
                MarketBar(ticker="SPY", date=date(2012, 1, 17), adjusted_close=20.0),
            ],
            [],
        )

    monkeypatch.setattr(market_data, "fetch_market_bars", fake_fetch_market_bars)

    bars, missing = market_symbology.fetch_hu5_market_bars(
        ["MHP", "MHFI"],
        date(2012, 1, 16),
        date(2012, 1, 18),
        benchmark="SPY",
        cache_dir=tmp_path,
        cache_only=True,
    )

    assert captured["tickers"] == ["SPGI"]
    assert captured["benchmark"] == "SPY"
    assert missing == []
    assert {(bar.ticker, bar.adjusted_close) for bar in bars} == {
        ("MHP", 10.0),
        ("MHFI", 10.0),
        ("SPY", 20.0),
    }


def test_hu5_fetch_maps_provider_missing_back_to_every_historical_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch_market_bars(
        tickers: list[str],
        start: date,
        end: date,
        **kwargs: Any,
    ) -> tuple[list[MarketBar], list[str]]:
        return [], ["SPGI"]

    monkeypatch.setattr(market_data, "fetch_market_bars", fake_fetch_market_bars)

    bars, missing = market_symbology.fetch_hu5_market_bars(
        ["MHP", "MHFI"], date(2012, 1, 16), date(2012, 1, 18)
    )

    assert bars == []
    assert missing == ["MHFI", "MHP"]


def test_kft_frozen_event_windows_end_before_spin_off_cutoff() -> None:
    event = _event("kft-safe", "KFT", date(2012, 2, 27))
    bars = _weekday_bars("KFT", date(2012, 1, 1), date(2012, 12, 31))
    config = EventStudyConfig(
        windows=[
            EventWindow(start=1, end=21),
            EventWindow(start=1, end=63),
            EventWindow(start=1, end=126),
        ]
    )

    market_symbology.validate_hu5_market_alias_windows(
        [event], (_mapping(event.accession_number, "KFT"),), bars, config
    )


def test_kft_alias_fails_closed_when_event_window_crosses_spin_off_cutoff() -> None:
    event = _event("kft-crossing", "KFT", date(2012, 5, 1))
    bars = _weekday_bars("KFT", date(2012, 1, 1), date(2013, 2, 1))
    config = EventStudyConfig(
        windows=[EventWindow(start=1, end=126)]
    )

    with pytest.raises(market_symbology.HU5MarketSymbologyWindowError) as exc_info:
        market_symbology.validate_hu5_market_alias_windows(
            [event], (_mapping(event.accession_number, "KFT"),), bars, config
        )

    assert len(exc_info.value.issues) == 1
    issue = exc_info.value.issues[0]
    assert issue.historical_symbol == "KFT"
    assert issue.reason == "event_window_crosses_corporate_action_cutoff"
    assert issue.required_before == "2012-10-01"
    assert issue.endpoint_date is not None
    assert date.fromisoformat(issue.endpoint_date) >= date(2012, 10, 1)
