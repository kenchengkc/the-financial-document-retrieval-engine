"""Runtime daily-price fetcher for event studies.

Pulls dividend- and split-adjusted daily closes from the public Yahoo Finance
chart API (no API key) and returns ``MarketBar`` rows the event-study engine
consumes. Market data is fetched on demand and cached locally; it is never
committed (see the repo data policy).
"""

from __future__ import annotations

import contextlib
import json
import os
import time as time_module
from datetime import UTC, date, datetime, time
from pathlib import Path

import requests

from fdre.research.event_study import MarketBar

TIINGO_URL = "https://api.tiingo.com/tiingo/daily/{symbol}/prices"

CHART_HOSTS = (
    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
)
DEFAULT_CACHE_DIR = Path("data/cache/market")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _epoch(day: date) -> int:
    return int(datetime.combine(day, time.min, tzinfo=UTC).timestamp())


def open_yahoo_session() -> tuple[requests.Session, str | None]:
    """Establish a Yahoo session with anti-bot cookies + a crumb token."""
    session = requests.Session()
    session.headers.update(_HEADERS)
    for url in ("https://fc.yahoo.com/", "https://finance.yahoo.com/"):
        with contextlib.suppress(requests.RequestException):
            session.get(url, timeout=10)
    crumb = None
    try:
        response = session.get(
            "https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10
        )
        text = response.text.strip()
        if response.ok and text and "<" not in text and "Too Many" not in text:
            crumb = text
    except requests.RequestException:
        pass
    return session, crumb


def fetch_ticker_bars(
    ticker: str,
    start: date,
    end: date,
    *,
    session: requests.Session | None = None,
    crumb: str | None = None,
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
    timeout: float = 25.0,
) -> list[MarketBar]:
    """Daily adjusted closes for one ticker over [start, end]."""
    cache_path = None
    if cache_dir is not None:
        cache_path = Path(cache_dir) / f"{ticker.upper()}_{start:%Y%m%d}_{end:%Y%m%d}.json"
        if cache_path.exists():
            return _parse_chart(ticker, json.loads(cache_path.read_text()))

    http = session or requests
    params: dict[str, object] = {
        "period1": _epoch(start),
        "period2": _epoch(end),
        "interval": "1d",
        "events": "div,split",
    }
    if crumb:
        params["crumb"] = crumb
    payload: dict | None = None
    for host in CHART_HOSTS:
        for attempt in range(4):
            response = http.get(host.format(symbol=ticker.upper()), params=params, timeout=timeout)
            if response.status_code == 429:
                time_module.sleep(2.0 * (attempt + 1))
                continue
            response.raise_for_status()
            payload = response.json()
            break
        if payload is not None:
            break
    if payload is None:
        return []
    bars = _parse_chart(ticker, payload)
    if cache_path is not None and bars:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload))
    return bars


def fetch_ticker_bars_tiingo(
    ticker: str,
    start: date,
    end: date,
    token: str,
    *,
    session: requests.Session | None = None,
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
    timeout: float = 25.0,
) -> list[MarketBar]:
    """Daily adjusted closes for one ticker from Tiingo (requires a free token)."""
    cache_path = None
    if cache_dir is not None:
        cache_path = Path(cache_dir) / f"tiingo_{ticker.upper()}_{start:%Y%m%d}_{end:%Y%m%d}.json"
        if cache_path.exists():
            rows = json.loads(cache_path.read_text())
            return _parse_tiingo(ticker, rows)
    http = session or requests
    response = http.get(
        TIINGO_URL.format(symbol=ticker.lower()),
        params={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "format": "json",
            "token": token,
        },
        timeout=timeout,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    rows = response.json()
    bars = _parse_tiingo(ticker, rows)
    if cache_path is not None and bars:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(rows))
    return bars


def _parse_tiingo(ticker: str, rows: list[dict]) -> list[MarketBar]:
    bars: list[MarketBar] = []
    for row in rows or []:
        price = row.get("adjClose")
        day = row.get("date")
        if price is None or not day or price <= 0:
            continue
        bars.append(
            MarketBar(
                ticker=ticker.upper(),
                date=date.fromisoformat(str(day)[:10]),
                adjusted_close=float(price),
            )
        )
    return bars


def fetch_market_bars(
    tickers: list[str],
    start: date,
    end: date,
    *,
    benchmark: str = "SPY",
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
    pause: float = 0.5,
    tiingo_token: str | None = None,
) -> tuple[list[MarketBar], list[str]]:
    """Fetch bars for ``tickers`` plus the benchmark. Returns (bars, missing).

    Uses Tiingo when a token is available (``tiingo_token`` arg or the
    ``TIINGO_API_KEY`` env var) — reliable and reproducible — otherwise falls
    back to the keyless Yahoo chart API (best-effort, rate-limited).
    """
    token = tiingo_token or os.environ.get("TIINGO_API_KEY")
    wanted = list(dict.fromkeys([benchmark.upper(), *(t.upper() for t in tickers)]))
    session = requests.Session()
    crumb = None
    if not token:
        session, crumb = open_yahoo_session()
    bars: list[MarketBar] = []
    missing: list[str] = []
    for symbol in wanted:
        try:
            if token:
                ticker_bars = fetch_ticker_bars_tiingo(
                    symbol, start, end, token, session=session, cache_dir=cache_dir
                )
            else:
                ticker_bars = fetch_ticker_bars(
                    symbol, start, end, session=session, crumb=crumb, cache_dir=cache_dir
                )
        except requests.RequestException:
            ticker_bars = []
        if ticker_bars:
            bars.extend(ticker_bars)
        else:
            missing.append(symbol)
        time_module.sleep(pause if not token else 0.05)
    return bars, missing


def _parse_chart(ticker: str, payload: dict) -> list[MarketBar]:
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return []
    block = result[0]
    timestamps = block.get("timestamp") or []
    indicators = block.get("indicators") or {}
    adjclose_blocks = indicators.get("adjclose") or []
    closes = adjclose_blocks[0].get("adjclose") if adjclose_blocks else None
    if not closes:
        quote = (indicators.get("quote") or [{}])[0]
        closes = quote.get("close")
    if not closes:
        return []
    bars: list[MarketBar] = []
    for epoch, price in zip(timestamps, closes, strict=False):
        if price is None or price <= 0:
            continue
        bars.append(
            MarketBar(
                ticker=ticker.upper(),
                date=datetime.fromtimestamp(epoch, UTC).date(),
                adjusted_close=float(price),
            )
        )
    return bars
