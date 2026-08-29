from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import requests

from fdre.research.event_study import MarketBar
from fdre.research.market_data import (
    MarketDataRateLimitError,
    _covering_tiingo_path,
    fetch_market_bars,
    fetch_ticker_bars,
    fetch_ticker_bars_tiingo,
)


def _write_cache(cache_dir: Path, ticker: str, start: str, end: str, rows: list[dict]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"tiingo_{ticker}_{start}_{end}.json").write_text(json.dumps(rows))


def test_covering_cache_is_reused_for_narrower_window(tmp_path: Path) -> None:
    rows = [
        {"date": "2022-01-03", "adjClose": 100.0},
        {"date": "2023-06-01", "adjClose": 110.0},
        {"date": "2025-12-31", "adjClose": 120.0},
    ]
    _write_cache(tmp_path, "AAPL", "20220101", "20261231", rows)

    # A narrower request than any exact cache key still finds the covering file...
    assert (
        _covering_tiingo_path(tmp_path, "AAPL", date(2023, 1, 1), date(2024, 1, 1)) is not None
    )
    # ...and a non-covering request (earlier than the cache start) does not.
    assert _covering_tiingo_path(tmp_path, "AAPL", date(2020, 1, 1), date(2021, 1, 1)) is None

    # The fetch reuses it without any network/token use.
    bars = fetch_ticker_bars_tiingo(
        "AAPL", date(2023, 1, 1), date(2024, 1, 1), token="unused", cache_dir=tmp_path
    )
    assert date(2023, 6, 1) in {bar.date for bar in bars}


def test_fetch_market_bars_cache_only_reuses_covering_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [{"date": "2023-06-01", "adjClose": 110.0}]
    _write_cache(tmp_path, "SPY", "20220101", "20261231", rows)
    _write_cache(tmp_path, "MSFT", "20220101", "20261231", rows)

    # Requested window is narrower than the cached files; cache_only must not
    # report these as missing just because the exact key differs.
    def fail_on_network_session() -> None:
        raise AssertionError("cache-only mode must not initialize a network session")

    monkeypatch.setattr(
        "fdre.research.market_data.open_yahoo_session", fail_on_network_session
    )
    bars, missing = fetch_market_bars(
        ["MSFT"],
        date(2023, 1, 1),
        date(2024, 1, 1),
        benchmark="SPY",
        cache_dir=tmp_path,
        cache_only=True,
    )
    assert missing == []
    assert any(bar.ticker == "MSFT" for bar in bars)


def test_fetch_market_bars_falls_back_to_yahoo_when_tiingo_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TIINGO_API_KEY", "test-token")
    tiingo_calls: list[str] = []
    yahoo_calls: list[str] = []

    def fail_tiingo(ticker: str, *args: object, **kwargs: object) -> list[MarketBar]:
        tiingo_calls.append(ticker)
        raise requests.HTTPError("provider unavailable")

    def fake_open_yahoo_session() -> tuple[requests.Session, None]:
        return requests.Session(), None

    def fake_yahoo(ticker: str, *args: object, **kwargs: object) -> list[MarketBar]:
        yahoo_calls.append(ticker)
        return [MarketBar(ticker=ticker, date=date(2023, 6, 1), adjusted_close=100.0)]

    monkeypatch.setattr("fdre.research.market_data.fetch_ticker_bars_tiingo", fail_tiingo)
    monkeypatch.setattr("fdre.research.market_data.open_yahoo_session", fake_open_yahoo_session)
    monkeypatch.setattr("fdre.research.market_data.fetch_ticker_bars", fake_yahoo)

    bars, missing = fetch_market_bars(
        ["MSFT"],
        date(2023, 1, 1),
        date(2024, 1, 1),
        benchmark="SPY",
        cache_dir=tmp_path,
        pause=0,
    )

    assert missing == []
    assert {bar.ticker for bar in bars} == {"SPY", "MSFT"}
    assert tiingo_calls == ["SPY", "MSFT"]
    assert yahoo_calls == ["SPY", "MSFT"]


def test_fetch_market_bars_trips_provider_circuits_after_429(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TIINGO_API_KEY", "test-token")
    tiingo_calls: list[str] = []
    yahoo_calls: list[str] = []

    def rate_limited_tiingo(
        ticker: str, *args: object, **kwargs: object
    ) -> list[MarketBar]:
        tiingo_calls.append(ticker)
        raise MarketDataRateLimitError("tiingo", ticker)

    def fake_open_yahoo_session() -> tuple[requests.Session, None]:
        return requests.Session(), None

    def rate_limited_yahoo(
        ticker: str, *args: object, **kwargs: object
    ) -> list[MarketBar]:
        yahoo_calls.append(ticker)
        raise MarketDataRateLimitError("yahoo", ticker)

    monkeypatch.setattr(
        "fdre.research.market_data.fetch_ticker_bars_tiingo", rate_limited_tiingo
    )
    monkeypatch.setattr("fdre.research.market_data.open_yahoo_session", fake_open_yahoo_session)
    monkeypatch.setattr("fdre.research.market_data.fetch_ticker_bars", rate_limited_yahoo)

    bars, missing = fetch_market_bars(
        ["MSFT", "NVDA"],
        date(2023, 1, 1),
        date(2024, 1, 1),
        benchmark="SPY",
        cache_dir=tmp_path,
        pause=0,
    )

    assert bars == []
    assert missing == ["SPY", "MSFT", "NVDA"]
    assert tiingo_calls == ["SPY"]
    assert yahoo_calls == ["SPY"]


def test_yahoo_429_retries_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    class FakeResponse:
        status_code = 429

        def raise_for_status(self) -> None:
            raise AssertionError("429 should be handled before raise_for_status")

        def json(self) -> dict:
            return {}

    class FakeSession:
        def get(self, url: str, **kwargs: object) -> FakeResponse:
            calls.append(url)
            return FakeResponse()

    monkeypatch.setattr("fdre.research.market_data.time_module.sleep", sleeps.append)

    with pytest.raises(MarketDataRateLimitError):
        fetch_ticker_bars(
            "MSFT",
            date(2023, 1, 1),
            date(2024, 1, 1),
            session=FakeSession(),  # type: ignore[arg-type]
            cache_dir=None,
            rate_limit_retries=1,
        )

    assert len(calls) == 4
    assert sleeps == [2.0, 2.0]
