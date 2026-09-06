"""Bounded market-cache hydration for the frozen HU-5 amended study.

This module is intentionally operational: it only materializes adjusted-close
market-data cache entries. It never computes event returns, walk-forward folds,
or promotion decisions.
"""

from __future__ import annotations

import re
import time as time_module
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import requests

from fdre.research.event_study import MarketBar
from fdre.research.market_data import (
    MarketDataRateLimitError,
    fetch_ticker_bars,
    fetch_ticker_bars_tiingo,
    open_yahoo_session,
)
from fdre.research.market_symbology import hu5_provider_symbol

HYDRATION_SCHEMA_VERSION = "fdre-hu5-market-hydration-v1"
_TIINGO_CACHE_PATTERN = re.compile(
    r"^tiingo_(?P<ticker>.+)_(?P<start>\d{8})_(?P<end>\d{8})\.json$"
)


@dataclass(frozen=True, slots=True)
class HydrationRound:
    round_number: int
    attempted_symbols: tuple[str, ...]
    hydrated_symbols: tuple[str, ...]
    unavailable_symbols: tuple[str, ...]
    transient_symbols: tuple[str, ...]
    tiingo_rate_limited: bool
    yahoo_rate_limited: bool


@dataclass(frozen=True, slots=True)
class MarketHydrationReport:
    schema_version: str
    requested_start: str
    requested_end: str
    required_symbols: tuple[str, ...]
    initial_covered_symbols: tuple[str, ...]
    final_covered_symbols: tuple[str, ...]
    hydrated_symbols: tuple[str, ...]
    unavailable_symbols: tuple[str, ...]
    remaining_symbols: tuple[str, ...]
    rounds: tuple[HydrationRound, ...]

    @property
    def coverage_complete(self) -> bool:
        return not self.remaining_symbols

    def as_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "required_symbol_count": len(self.required_symbols),
            "required_symbols": list(self.required_symbols),
            "initial_covered_count": len(self.initial_covered_symbols),
            "initial_covered_symbols": list(self.initial_covered_symbols),
            "final_covered_count": len(self.final_covered_symbols),
            "final_covered_symbols": list(self.final_covered_symbols),
            "hydrated_count": len(self.hydrated_symbols),
            "hydrated_symbols": list(self.hydrated_symbols),
            "unavailable_count": len(self.unavailable_symbols),
            "unavailable_symbols": list(self.unavailable_symbols),
            "remaining_count": len(self.remaining_symbols),
            "remaining_symbols": list(self.remaining_symbols),
            "coverage_complete": self.coverage_complete,
            "rounds": [asdict(item) for item in self.rounds],
        }


def covered_market_symbols(
    cache_dir: Path,
    symbols: list[str] | tuple[str, ...],
    start: date,
    end: date,
) -> set[str]:
    """Return historical symbols covered by their frozen provider cache symbols."""
    wanted = {symbol.upper() for symbol in symbols}
    covered: set[str] = set()
    if not cache_dir.exists():
        return covered

    start_token = start.strftime("%Y%m%d")
    end_token = end.strftime("%Y%m%d")
    for historical_symbol in wanted:
        provider_symbol = hu5_provider_symbol(historical_symbol)
        prefix = f"tiingo_{provider_symbol}_"
        for path in cache_dir.glob(f"{prefix}*.json"):
            match = _TIINGO_CACHE_PATTERN.fullmatch(path.name)
            if match is None:
                continue
            cached_start = _parse_cache_date(match.group("start"))
            cached_end = _parse_cache_date(match.group("end"))
            if cached_start <= start and cached_end >= end:
                covered.add(historical_symbol)
                break
        if historical_symbol in covered:
            continue
        yahoo_path = cache_dir / f"{provider_symbol}_{start_token}_{end_token}.json"
        if yahoo_path.exists():
            covered.add(historical_symbol)
    return covered


def run_market_cache_hydration(
    symbols: list[str] | tuple[str, ...],
    start: date,
    end: date,
    *,
    token: str,
    cache_dir: Path,
    batch_size: int = 45,
    max_rounds: int = 6,
    sleep_seconds: float = 3900.0,
    pause_seconds: float = 0.5,
) -> MarketHydrationReport:
    """Hydrate a fixed market-data window without evaluating research outcomes.

    Each round attempts at most ``batch_size`` previously uncovered historical
    symbols. Provider aliases are used only for network/cache addressing. Provider-
    wide rate limits stop further use of that provider for the round. Between rounds
    the caller sleeps long enough for an hourly provider quota to reset. Symbols for
    which both providers return an explicit no-data response are retained as terminal
    unavailable evidence rather than retried forever.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if max_rounds <= 0:
        raise ValueError("max_rounds must be positive")
    if sleep_seconds < 0:
        raise ValueError("sleep_seconds must be non-negative")
    if pause_seconds < 0:
        raise ValueError("pause_seconds must be non-negative")
    if not token.strip():
        raise ValueError("Tiingo token is required for HU-5 cache hydration")

    required = tuple(sorted({symbol.upper() for symbol in symbols}))
    if not required:
        raise ValueError("at least one market symbol is required")
    cache_dir.mkdir(parents=True, exist_ok=True)
    initial_covered = covered_market_symbols(cache_dir, required, start, end)
    terminal_unavailable: set[str] = set()
    hydrated: set[str] = set()
    rounds: list[HydrationRound] = []

    for round_number in range(1, max_rounds + 1):
        covered = covered_market_symbols(cache_dir, required, start, end)
        pending = [
            symbol
            for symbol in required
            if symbol not in covered and symbol not in terminal_unavailable
        ]
        if not pending:
            break

        round_report = _hydrate_round(
            pending,
            start,
            end,
            token=token,
            cache_dir=cache_dir,
            batch_size=batch_size,
            pause_seconds=pause_seconds,
            round_number=round_number,
        )
        rounds.append(round_report)
        hydrated.update(round_report.hydrated_symbols)
        terminal_unavailable.update(round_report.unavailable_symbols)

        covered_after = covered_market_symbols(cache_dir, required, start, end)
        actionable = [
            symbol
            for symbol in required
            if symbol not in covered_after and symbol not in terminal_unavailable
        ]
        if not actionable or round_number >= max_rounds:
            break
        if sleep_seconds:
            time_module.sleep(sleep_seconds)

    final_covered = covered_market_symbols(cache_dir, required, start, end)
    remaining = tuple(sorted(set(required) - final_covered))
    return MarketHydrationReport(
        schema_version=HYDRATION_SCHEMA_VERSION,
        requested_start=start.isoformat(),
        requested_end=end.isoformat(),
        required_symbols=required,
        initial_covered_symbols=tuple(sorted(initial_covered)),
        final_covered_symbols=tuple(sorted(final_covered)),
        hydrated_symbols=tuple(sorted(hydrated)),
        unavailable_symbols=tuple(sorted(terminal_unavailable)),
        remaining_symbols=remaining,
        rounds=tuple(rounds),
    )


def _hydrate_round(
    pending: list[str],
    start: date,
    end: date,
    *,
    token: str,
    cache_dir: Path,
    batch_size: int,
    pause_seconds: float,
    round_number: int,
) -> HydrationRound:
    session = requests.Session()
    yahoo_session: requests.Session | None = None
    yahoo_crumb: str | None = None
    tiingo_rate_limited = False
    yahoo_rate_limited = False
    attempted: list[str] = []
    hydrated: list[str] = []
    unavailable: list[str] = []
    transient: list[str] = []

    for historical_symbol in pending:
        if len(attempted) >= batch_size:
            break
        if tiingo_rate_limited and yahoo_rate_limited:
            break

        attempted.append(historical_symbol)
        provider_symbol = hu5_provider_symbol(historical_symbol)
        tiingo_empty = False
        tiingo_transient = False
        bars: list[MarketBar] = []

        if not tiingo_rate_limited:
            try:
                bars = fetch_ticker_bars_tiingo(
                    provider_symbol,
                    start,
                    end,
                    token,
                    session=session,
                    cache_dir=cache_dir,
                )
                tiingo_empty = not bars
            except MarketDataRateLimitError:
                tiingo_rate_limited = True
                tiingo_transient = True
            except requests.RequestException:
                tiingo_transient = True

        if bars:
            hydrated.append(historical_symbol)
            if pause_seconds:
                time_module.sleep(pause_seconds)
            continue

        yahoo_empty = False
        yahoo_transient = False
        if not yahoo_rate_limited:
            if yahoo_session is None:
                yahoo_session, yahoo_crumb = open_yahoo_session()
            try:
                bars = fetch_ticker_bars(
                    provider_symbol,
                    start,
                    end,
                    session=yahoo_session,
                    crumb=yahoo_crumb,
                    cache_dir=cache_dir,
                )
                yahoo_empty = not bars
            except MarketDataRateLimitError:
                yahoo_rate_limited = True
                yahoo_transient = True
            except requests.RequestException:
                yahoo_transient = True

        if bars:
            hydrated.append(historical_symbol)
        elif tiingo_empty and yahoo_empty:
            unavailable.append(historical_symbol)
        elif tiingo_transient or yahoo_transient or tiingo_rate_limited or yahoo_rate_limited:
            transient.append(historical_symbol)
        else:
            transient.append(historical_symbol)

        if pause_seconds:
            time_module.sleep(pause_seconds)

    return HydrationRound(
        round_number=round_number,
        attempted_symbols=tuple(attempted),
        hydrated_symbols=tuple(hydrated),
        unavailable_symbols=tuple(unavailable),
        transient_symbols=tuple(transient),
        tiingo_rate_limited=tiingo_rate_limited,
        yahoo_rate_limited=yahoo_rate_limited,
    )


def _parse_cache_date(value: str) -> date:
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
