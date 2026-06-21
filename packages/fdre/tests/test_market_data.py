from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fdre.research.market_data import (
    _covering_tiingo_path,
    fetch_market_bars,
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


def test_fetch_market_bars_cache_only_reuses_covering_caches(tmp_path: Path) -> None:
    rows = [{"date": "2023-06-01", "adjClose": 110.0}]
    _write_cache(tmp_path, "SPY", "20220101", "20261231", rows)
    _write_cache(tmp_path, "MSFT", "20220101", "20261231", rows)

    # Requested window is narrower than the cached files; cache_only must not
    # report these as missing just because the exact key differs.
    bars, missing = fetch_market_bars(
        ["MSFT"],
        date(2023, 1, 1),
        date(2024, 1, 1),
        benchmark="SPY",
        cache_dir=tmp_path,
        tiingo_token="unused",
        cache_only=True,
    )
    assert missing == []
    assert any(bar.ticker == "MSFT" for bar in bars)
