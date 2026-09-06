from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from fdre.research import market_data, market_symbology

START = date(2012, 1, 16)
END = date(2012, 1, 18)


def _write_tiingo_cache(cache_dir: Path, symbol: str, price: float) -> None:
    path = cache_dir / f"tiingo_{symbol}_{START:%Y%m%d}_{END:%Y%m%d}.json"
    path.write_text(
        '[{"date":"2012-01-17T00:00:00Z","adjClose":' + str(price) + "}]"
    )


def test_generic_market_fetch_is_identity_mapped_without_explicit_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FDRE_MARKET_SYMBOLOGY_PROFILE", raising=False)
    _write_tiingo_cache(tmp_path, "SPY", 20.0)
    _write_tiingo_cache(tmp_path, "MHP", 10.0)

    bars, missing = market_data.fetch_market_bars(
        ["MHP"],
        START,
        END,
        benchmark="SPY",
        cache_dir=tmp_path,
        cache_only=True,
    )

    assert missing == []
    assert {(bar.ticker, bar.adjusted_close) for bar in bars} == {
        ("MHP", 10.0),
        ("SPY", 20.0),
    }


def test_explicit_hu5_profile_queries_provider_cache_and_relabels_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "FDRE_MARKET_SYMBOLOGY_PROFILE",
        market_symbology.HU5_MARKET_SYMBOLOGY_SCHEMA_VERSION,
    )
    _write_tiingo_cache(tmp_path, "SPY", 20.0)
    _write_tiingo_cache(tmp_path, "SPGI", 10.0)

    bars, missing = market_data.fetch_market_bars(
        ["MHP", "MHFI"],
        START,
        END,
        benchmark="SPY",
        cache_dir=tmp_path,
        cache_only=True,
    )

    assert missing == []
    assert {(bar.ticker, bar.adjusted_close) for bar in bars} == {
        ("MHP", 10.0),
        ("MHFI", 10.0),
        ("SPY", 20.0),
    }
    assert all(bar.ticker != "SPGI" for bar in bars)


def test_unknown_market_symbology_profile_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDRE_MARKET_SYMBOLOGY_PROFILE", "not-a-real-profile")

    with pytest.raises(ValueError, match="unknown market symbology profile"):
        market_data.fetch_market_bars(
            ["MHP"], START, END, cache_only=True, max_uncached_fetches=0
        )
