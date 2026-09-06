from __future__ import annotations

from datetime import date
from pathlib import Path

import requests

from fdre.research import hu5_market_hydration as hydration
from fdre.research.event_study import MarketBar
from fdre.research.market_data import MarketDataRateLimitError

START = date(2012, 1, 16)
END = date(2027, 4, 19)


def _write_tiingo_cache(cache_dir: Path, symbol: str) -> None:
    path = cache_dir / f"tiingo_{symbol}_{START:%Y%m%d}_{END:%Y%m%d}.json"
    path.write_text('[{"date":"2012-01-17T00:00:00Z","adjClose":10.0}]')


def _bar(symbol: str) -> MarketBar:
    return MarketBar(ticker=symbol, date=date(2012, 1, 17), adjusted_close=10.0)


def test_covered_market_symbols_matches_canonical_cache_semantics(tmp_path: Path) -> None:
    (tmp_path / "tiingo_A_20100101_20300101.json").write_text("[]")
    (tmp_path / "B_20100101_20300101.json").write_text("{}")
    (tmp_path / f"C_{START:%Y%m%d}_{END:%Y%m%d}.json").write_text("{}")

    covered = hydration.covered_market_symbols(tmp_path, ["A", "B", "C"], START, END)

    assert covered == {"A", "C"}


def test_hydration_skips_terminal_no_data_and_respects_round_batch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tiingo_calls: list[str] = []
    yahoo_calls: list[str] = []

    def fake_tiingo(symbol: str, *args, **kwargs):
        tiingo_calls.append(symbol)
        if symbol == "B":
            return []
        _write_tiingo_cache(tmp_path, symbol)
        return [_bar(symbol)]

    def fake_yahoo(symbol: str, *args, **kwargs):
        yahoo_calls.append(symbol)
        return []

    monkeypatch.setattr(hydration, "fetch_ticker_bars_tiingo", fake_tiingo)
    monkeypatch.setattr(hydration, "fetch_ticker_bars", fake_yahoo)
    monkeypatch.setattr(
        hydration,
        "open_yahoo_session",
        lambda: (requests.Session(), None),
    )

    report = hydration.run_market_cache_hydration(
        ["A", "B", "C"],
        START,
        END,
        token="token",
        cache_dir=tmp_path,
        batch_size=2,
        max_rounds=2,
        sleep_seconds=0,
        pause_seconds=0,
    )

    assert tiingo_calls == ["A", "B", "C"]
    assert yahoo_calls == ["B"]
    assert report.hydrated_symbols == ("A", "C")
    assert report.unavailable_symbols == ("B",)
    assert report.remaining_symbols == ("B",)
    assert report.coverage_complete is False
    assert len(report.rounds) == 2
    assert report.rounds[0].attempted_symbols == ("A", "B")
    assert report.rounds[1].attempted_symbols == ("C",)


def test_hydration_recovers_after_provider_rate_limit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    def fake_tiingo(symbol: str, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise MarketDataRateLimitError("tiingo", symbol)
        _write_tiingo_cache(tmp_path, symbol)
        return [_bar(symbol)]

    def fake_yahoo(symbol: str, *args, **kwargs):
        raise MarketDataRateLimitError("yahoo", symbol)

    monkeypatch.setattr(hydration, "fetch_ticker_bars_tiingo", fake_tiingo)
    monkeypatch.setattr(hydration, "fetch_ticker_bars", fake_yahoo)
    monkeypatch.setattr(
        hydration,
        "open_yahoo_session",
        lambda: (requests.Session(), None),
    )

    report = hydration.run_market_cache_hydration(
        ["A"],
        START,
        END,
        token="token",
        cache_dir=tmp_path,
        batch_size=1,
        max_rounds=2,
        sleep_seconds=0,
        pause_seconds=0,
    )

    assert calls == 2
    assert report.coverage_complete is True
    assert report.final_covered_symbols == ("A",)
    assert report.rounds[0].tiingo_rate_limited is True
    assert report.rounds[0].yahoo_rate_limited is True
    assert report.rounds[1].hydrated_symbols == ("A",)
