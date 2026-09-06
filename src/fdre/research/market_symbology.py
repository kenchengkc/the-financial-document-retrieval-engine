"""Frozen HU-5 market-provider symbology and historical-ticker relabeling.

This layer changes only provider addressing. Historical event/security symbols remain
unchanged throughout universe lineage and outcome mapping.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fdre.research.event_study import EventStudyConfig, FilingEvent, MarketBar
from fdre.research.hu5_multiclass import HU5EventOutcomeMapping
from fdre.research.market_data import DEFAULT_CACHE_DIR, fetch_market_bars

HU5_MARKET_SYMBOLOGY_SCHEMA_VERSION = "fdre-hu5-market-symbology-v1"
HU5_MARKET_SYMBOLOGY_MANIFEST_ID = (
    "89c67316e1417682519996ea2d387a44802b2eb63c225f22cf87aca29db6c328"
)


@dataclass(frozen=True, slots=True)
class HU5MarketSymbolAlias:
    historical_symbol: str
    provider: str
    provider_symbol: str
    continuity: str
    effective_date: str
    event_window_end_before: str | None
    evidence_url: str


@dataclass(frozen=True, slots=True)
class HU5MarketAliasWindowIssue:
    accession_number: str
    historical_symbol: str
    window: str
    reason: str
    endpoint_date: str | None
    required_before: str | None


class HU5MarketSymbologyWindowError(ValueError):
    """Raised before scoring when a restricted alias would cross its frozen cutoff."""

    def __init__(self, issues: tuple[HU5MarketAliasWindowIssue, ...]) -> None:
        self.issues = issues
        super().__init__(
            f"{len(issues)} HU-5 market symbology event-window constraints failed"
        )


HU5_MARKET_SYMBOL_ALIASES: tuple[HU5MarketSymbolAlias, ...] = (
    HU5MarketSymbolAlias(
        historical_symbol="BLL",
        provider="tiingo",
        provider_symbol="BALL",
        continuity="ticker_rename",
        effective_date="2022-05-10",
        event_window_end_before=None,
        evidence_url=(
            "https://www.ball.com/our-company/ball-stories/ticker-symbol-changed-to-ball"
        ),
    ),
    HU5MarketSymbolAlias(
        historical_symbol="KFT",
        provider="tiingo",
        provider_symbol="MDLZ",
        continuity="spin_off_pre_event_window_only",
        effective_date="2012-10-02",
        event_window_end_before="2012-10-01",
        evidence_url=(
            "https://www.mondelezinternational.com/investors/stock/spin-off-information/"
        ),
    ),
    HU5MarketSymbolAlias(
        historical_symbol="MHFI",
        provider="tiingo",
        provider_symbol="SPGI",
        continuity="ticker_rename",
        effective_date="2016-04-28",
        event_window_end_before=None,
        evidence_url=(
            "https://investor.spglobal.com/contact-investor-relations/investor-faq/"
        ),
    ),
    HU5MarketSymbolAlias(
        historical_symbol="MHP",
        provider="tiingo",
        provider_symbol="SPGI",
        continuity="ticker_rename_chain",
        effective_date="2013-05-14",
        event_window_end_before=None,
        evidence_url=(
            "https://press.spglobal.com/2013-05-14-McGraw-Hill-Financial-to-Begin-"
            "NYSE-Trading-Under-New-MHFI-Stock-Symbol-on-Tuesday-May-14-at-the-Opening-Bell"
        ),
    ),
    HU5MarketSymbolAlias(
        historical_symbol="MMC",
        provider="tiingo",
        provider_symbol="MRSH",
        continuity="ticker_rename",
        effective_date="2026-01-14",
        event_window_end_before=None,
        evidence_url=(
            "https://www.marsh.com/en/corp/about/news/"
            "marsh-mclennan-to-change-nyse-symbol-to-mrsh.html"
        ),
    ),
    HU5MarketSymbolAlias(
        historical_symbol="PKI",
        provider="tiingo",
        provider_symbol="RVTY",
        continuity="ticker_rename",
        effective_date="2023-05-16",
        event_window_end_before=None,
        evidence_url=(
            "https://news.revvity.com/press-announcements/press-releases/"
            "press-release-details/2023/"
            "Revvity-Announces-Financial-Results-for-the-First-Quarter-of-2023/default.aspx"
        ),
    ),
    HU5MarketSymbolAlias(
        historical_symbol="TMK",
        provider="tiingo",
        provider_symbol="GL",
        continuity="ticker_rename",
        effective_date="2019-08-09",
        event_window_end_before=None,
        evidence_url=(
            "https://investors.globelifeinsurance.com/news-releases/2019/august/"
            "torchmark-corporation-has-officially-been-renamed-globe-life-inc"
            "?accessibility=true"
        ),
    ),
)

_ALIAS_BY_HISTORICAL = {
    item.historical_symbol: item for item in HU5_MARKET_SYMBOL_ALIASES
}


def hu5_market_symbology_manifest_payload() -> dict[str, object]:
    """Canonical payload frozen in the v1 research note."""
    return {
        "schema_version": HU5_MARKET_SYMBOLOGY_SCHEMA_VERSION,
        "aliases": [asdict(item) for item in HU5_MARKET_SYMBOL_ALIASES],
    }


def computed_hu5_market_symbology_manifest_id() -> str:
    payload = hu5_market_symbology_manifest_payload()
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def assert_frozen_hu5_market_symbology_manifest() -> None:
    observed = computed_hu5_market_symbology_manifest_id()
    if observed != HU5_MARKET_SYMBOLOGY_MANIFEST_ID:
        raise RuntimeError(
            "HU-5 market symbology manifest drifted: "
            f"expected {HU5_MARKET_SYMBOLOGY_MANIFEST_ID}, observed {observed}"
        )


def hu5_provider_symbol(historical_symbol: str) -> str:
    historical = historical_symbol.upper()
    alias = _ALIAS_BY_HISTORICAL.get(historical)
    return alias.provider_symbol if alias is not None else historical


def fetch_hu5_market_bars(
    historical_symbols: list[str],
    start: date,
    end: date,
    *,
    benchmark: str = "SPY",
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
    cache_only: bool = False,
    max_uncached_fetches: int | None = None,
) -> tuple[list[MarketBar], list[str]]:
    """Fetch using provider symbols and relabel bars back to historical symbols."""
    assert_frozen_hu5_market_symbology_manifest()
    historical = tuple(dict.fromkeys(symbol.upper() for symbol in historical_symbols))
    provider_by_historical = {
        symbol: hu5_provider_symbol(symbol) for symbol in historical
    }
    provider_symbols = list(dict.fromkeys(provider_by_historical.values()))
    provider_bars, missing_provider_symbols = fetch_market_bars(
        provider_symbols,
        start,
        end,
        benchmark=benchmark,
        cache_dir=cache_dir,
        cache_only=cache_only,
        max_uncached_fetches=max_uncached_fetches,
    )

    reverse: dict[str, set[str]] = defaultdict(set)
    for historical_symbol, provider_symbol in provider_by_historical.items():
        reverse[provider_symbol].add(historical_symbol)
    reverse[benchmark.upper()].add(benchmark.upper())

    relabeled: list[MarketBar] = []
    for bar in provider_bars:
        provider_symbol = bar.ticker.upper()
        targets = reverse.get(provider_symbol, {provider_symbol})
        for target in sorted(targets):
            if target == provider_symbol:
                relabeled.append(bar)
            else:
                relabeled.append(bar.model_copy(update={"ticker": target}))

    missing_provider = {symbol.upper() for symbol in missing_provider_symbols}
    missing_historical = {
        historical_symbol
        for historical_symbol, provider_symbol in provider_by_historical.items()
        if provider_symbol in missing_provider
    }
    if benchmark.upper() in missing_provider:
        missing_historical.add(benchmark.upper())
    return relabeled, sorted(missing_historical)


def validate_hu5_market_alias_windows(
    events: list[FilingEvent],
    mappings: tuple[HU5EventOutcomeMapping, ...],
    bars: list[MarketBar],
    config: EventStudyConfig,
) -> None:
    """Enforce event-window cutoffs for non-rename provider aliases.

    The current v1 restricted case is KFT: every required endpoint must precede
    the 2012-10-01 Kraft Foods Group distribution date.
    """
    assert_frozen_hu5_market_symbology_manifest()
    mapping_by_accession = {item.accession_number: item for item in mappings}
    bars_by_ticker: dict[str, list[MarketBar]] = defaultdict(list)
    for bar in bars:
        bars_by_ticker[bar.ticker.upper()].append(bar)
    for ticker_bars in bars_by_ticker.values():
        ticker_bars.sort(key=lambda item: item.date)

    issues: list[HU5MarketAliasWindowIssue] = []
    for event in events:
        mapping = mapping_by_accession.get(event.accession_number)
        if mapping is None:
            raise ValueError(f"missing HU-5 outcome mapping for {event.accession_number}")
        for symbol in mapping.symbols:
            alias = _ALIAS_BY_HISTORICAL.get(symbol.upper())
            if alias is None or alias.event_window_end_before is None:
                continue
            cutoff = date.fromisoformat(alias.event_window_end_before)
            ticker_bars = bars_by_ticker.get(symbol.upper(), [])
            event_index = _event_session_index(event, ticker_bars, config)
            if event_index is None:
                issues.append(
                    HU5MarketAliasWindowIssue(
                        accession_number=event.accession_number,
                        historical_symbol=symbol.upper(),
                        window="*",
                        reason="event_session_unavailable",
                        endpoint_date=None,
                        required_before=alias.event_window_end_before,
                    )
                )
                continue
            for window in config.windows:
                end_index = event_index + window.end
                if end_index >= len(ticker_bars):
                    issues.append(
                        HU5MarketAliasWindowIssue(
                            accession_number=event.accession_number,
                            historical_symbol=symbol.upper(),
                            window=window.label,
                            reason="event_window_endpoint_unavailable",
                            endpoint_date=None,
                            required_before=alias.event_window_end_before,
                        )
                    )
                    continue
                endpoint = ticker_bars[end_index].date
                if endpoint >= cutoff:
                    issues.append(
                        HU5MarketAliasWindowIssue(
                            accession_number=event.accession_number,
                            historical_symbol=symbol.upper(),
                            window=window.label,
                            reason="event_window_crosses_corporate_action_cutoff",
                            endpoint_date=endpoint.isoformat(),
                            required_before=alias.event_window_end_before,
                        )
                    )
    if issues:
        raise HU5MarketSymbologyWindowError(tuple(issues))


def _event_session_index(
    event: FilingEvent,
    bars: list[MarketBar],
    config: EventStudyConfig,
) -> int | None:
    timezone = ZoneInfo(config.market_timezone)
    localized = event.available_at.astimezone(timezone)
    target_date = localized.date()
    if localized.time() >= config.market_close:
        target_date += timedelta(days=1)
    return next(
        (index for index, bar in enumerate(bars) if bar.date >= target_date),
        None,
    )
