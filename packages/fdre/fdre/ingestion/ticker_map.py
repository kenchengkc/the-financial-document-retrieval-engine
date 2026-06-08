from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fdre.ingestion.sec_client import normalize_cik

LISTED_COMPANIES_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "sample" / "listed_companies.json"
)


@dataclass(frozen=True, slots=True)
class CompanySeed:
    ticker: str
    cik: str
    name: str
    exchange: str


SAMPLE_COMPANIES: dict[str, CompanySeed] = {
    company.ticker: company
    for company in (
        CompanySeed("AAPL", "0000320193", "Apple Inc.", "Nasdaq"),
        CompanySeed("MSFT", "0000789019", "Microsoft Corporation", "Nasdaq"),
        CompanySeed("NVDA", "0001045810", "NVIDIA Corporation", "Nasdaq"),
        CompanySeed("AMZN", "0001018724", "Amazon.com, Inc.", "Nasdaq"),
        CompanySeed("GOOGL", "0001652044", "Alphabet Inc.", "Nasdaq"),
    )
}

DEFAULT_SAMPLE_TICKERS = tuple(SAMPLE_COMPANIES)


@lru_cache
def _load_listed_companies(path: Path = LISTED_COMPANIES_PATH) -> dict[str, CompanySeed]:
    if not path.is_file():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
    companies: dict[str, CompanySeed] = {}
    for row in payload.get("companies", []):
        cik = normalize_cik(str(row["cik"]))
        seed = CompanySeed(
            ticker=str(row["primary_ticker"]).upper(),
            cik=cik,
            name=str(row["name"]),
            exchange=str(row["exchange"]),
        )
        tickers = row.get("tickers") or [seed.ticker]
        for ticker in tickers:
            companies[str(ticker).upper()] = seed
    return companies


def listed_company_tickers() -> tuple[str, ...]:
    listed = _load_listed_companies()
    if listed:
        return tuple(sorted(listed))
    return DEFAULT_SAMPLE_TICKERS


def get_company_seed(ticker: str) -> CompanySeed:
    normalized_ticker = ticker.upper()
    listed = _load_listed_companies()
    company = listed.get(normalized_ticker) or SAMPLE_COMPANIES.get(normalized_ticker)
    if company is None:
        raise ValueError(f"Unsupported ticker {ticker!r}")
    return CompanySeed(
        ticker=company.ticker,
        cik=normalize_cik(company.cik),
        name=company.name,
        exchange=company.exchange,
    )
