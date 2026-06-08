from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from fdre.ingestion.ticker_map import LISTED_COMPANIES_PATH, SP500_TICKERS_PATH, get_company_seed

WIKIPEDIA_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
DEFAULT_OUTPUT = SP500_TICKERS_PATH


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def _load_wikipedia_symbols(*, user_agent: str) -> list[str]:
    response = httpx.get(
        WIKIPEDIA_SP500_URL,
        headers={"User-Agent": user_agent},
        timeout=60.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    match = re.search(r"<table[^>]*id=\"constituents\".*?</table>", response.text, re.S)
    if match is None:
        raise RuntimeError("Could not find S&P 500 constituents table on Wikipedia")
    rows = re.findall(r"<tr>(.*?)</tr>", match.group(0), re.S)
    symbols: list[str] = []
    for row in rows[1:]:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if not cells:
            continue
        symbol = re.sub(r"<[^>]+>", "", cells[0])
        symbol = _normalize_symbol(symbol)
        if symbol:
            symbols.append(symbol)
    if not symbols:
        raise RuntimeError("No S&P 500 symbols parsed from Wikipedia")
    return symbols


def build_sp500_tickers(*, user_agent: str) -> dict[str, Any]:
    symbols = _load_wikipedia_symbols(user_agent=user_agent)
    primary_tickers: list[str] = []
    aliases: dict[str, str] = {}
    missing: list[str] = []

    for symbol in symbols:
        candidates = [symbol]
        if "-" in symbol:
            candidates.append(symbol.replace("-", "."))
        resolved = False
        for candidate in candidates:
            try:
                seed = get_company_seed(candidate)
            except ValueError:
                continue
            primary = seed.ticker
            if primary not in primary_tickers:
                primary_tickers.append(primary)
            aliases[symbol] = primary
            resolved = True
            break
        if not resolved:
            missing.append(symbol)

    primary_tickers.sort()
    return {
        "source": "wikipedia:List_of_S%26P_500_companies + fdre listed_companies.json",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "constituent_count": len(symbols),
        "primary_ticker_count": len(primary_tickers),
        "missing_from_catalog": missing,
        "aliases": aliases,
        "primary_tickers": primary_tickers,
    }


def write_sp500_tickers(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build S&P 500 primary ticker batch list")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--user-agent",
        default="FDRE build-sp500 contact@example.com",
        help="Descriptive user agent for Wikipedia",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not LISTED_COMPANIES_PATH.is_file():
        raise SystemExit(f"Missing catalog file: {LISTED_COMPANIES_PATH}")
    payload = build_sp500_tickers(user_agent=args.user_agent)
    write_sp500_tickers(args.output, payload)
    print(
        {
            "primary_tickers": payload["primary_ticker_count"],
            "missing_from_catalog": len(payload["missing_from_catalog"]),
            "output": str(args.output),
        }
    )


if __name__ == "__main__":
    main()
