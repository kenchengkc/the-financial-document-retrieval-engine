from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import httpx

from fdre.ingestion.sec_client import normalize_cik

SEC_COMPANY_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
NASDAQ_TRADED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
DEFAULT_OUTPUT = Path("data/sample/listed_companies.json")
ALLOWED_EXCHANGES = frozenset({"Nasdaq", "NYSE"})
ETF_NAME_MARKERS = (
    " ETF",
    " ETN",
    " EXCHANGE-TRADED",
    "/UNIT",
    "/RIGHT",
    "/WARRANT",
    "/NOTES",
)


@dataclass(frozen=True, slots=True)
class ListedCompanyRecord:
    cik: str
    name: str
    exchange: str
    primary_ticker: str
    tickers: tuple[str, ...]


def _looks_like_etf(name: str) -> bool:
    upper = name.upper()
    if any(marker in upper for marker in ETF_NAME_MARKERS):
        return True
    if upper.endswith(" FUND") and "MUTUAL" not in upper:
        return True
    if "SPDR" in upper and "TRUST" in upper:
        return True
    return upper.startswith("PROSHARES ") or upper.startswith("ISHARES ")


def _load_nasdaq_symbol_flags(*, client: httpx.Client) -> tuple[set[str], set[str]]:
    response = client.get(NASDAQ_TRADED_URL)
    response.raise_for_status()
    reader = csv.DictReader(StringIO(response.text), delimiter="|")
    etf_symbols: set[str] = set()
    test_symbols: set[str] = set()
    for row in reader:
        symbol = (row.get("Symbol") or "").strip().upper()
        if not symbol:
            continue
        if row.get("ETF") == "Y":
            etf_symbols.add(symbol)
        if row.get("Test Issue") == "Y":
            test_symbols.add(symbol)
    return etf_symbols, test_symbols


def _load_sec_exchange_rows(
    *,
    client: httpx.Client,
    user_agent: str,
) -> list[tuple[int, str, str, str]]:
    response = client.get(
        SEC_COMPANY_TICKERS_EXCHANGE_URL,
        headers={"User-Agent": user_agent},
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload["data"]
    parsed: list[tuple[int, str, str, str]] = []
    for row in rows:
        cik, name, ticker, exchange = row
        parsed.append((int(cik), str(name), str(ticker).upper(), str(exchange)))
    return parsed


def build_listed_companies(*, user_agent: str) -> list[ListedCompanyRecord]:
    with httpx.Client(timeout=60.0) as client:
        etf_symbols, test_symbols = _load_nasdaq_symbol_flags(client=client)
        rows = _load_sec_exchange_rows(client=client, user_agent=user_agent)

    grouped: dict[str, list[tuple[int, str, str, str]]] = defaultdict(list)
    for cik_int, name, ticker, exchange in rows:
        if exchange not in ALLOWED_EXCHANGES:
            continue
        if ticker in etf_symbols or ticker in test_symbols:
            continue
        if _looks_like_etf(name):
            continue
        grouped[normalize_cik(str(cik_int))].append((cik_int, name, ticker, exchange))

    companies: list[ListedCompanyRecord] = []
    for cik, entries in grouped.items():
        entries.sort(key=lambda item: item[2])
        _, name, primary_ticker, exchange = entries[0]
        tickers = tuple(sorted({entry[2] for entry in entries}))
        companies.append(
            ListedCompanyRecord(
                cik=cik,
                name=name,
                exchange=exchange,
                primary_ticker=primary_ticker,
                tickers=tickers,
            )
        )

    companies.sort(key=lambda company: company.primary_ticker)
    return companies


def write_listed_companies(path: Path, companies: list[ListedCompanyRecord]) -> None:
    payload: dict[str, Any] = {
        "source": "sec:company_tickers_exchange.json + nasdaqtraded.txt",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "company_count": len(companies),
        "companies": [
            {
                **asdict(company),
                "tickers": list(company.tickers),
            }
            for company in companies
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build NASDAQ/NYSE company seeds (one CIK per company, no ETFs)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output JSON path",
    )
    parser.add_argument(
        "--user-agent",
        default="FDRE build-list contact@example.com",
        help="Descriptive SEC user agent",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    companies = build_listed_companies(user_agent=args.user_agent)
    write_listed_companies(args.output, companies)
    print({"companies": len(companies), "output": str(args.output)})


if __name__ == "__main__":
    main()
