from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fdre.ingestion.sec_client import normalize_cik

LISTED_COMPANIES_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "sample" / "listed_companies.json"
)
SP500_TICKERS_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "sample" / "sp500_tickers.json"
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

# Fixed, liquid, cross-sector universe for deeper point-in-time research history.
RESEARCH_UNIVERSE_TICKERS = (
    "AAPL",
    "ABBV",
    "ABT",
    "ADBE",
    "AMD",
    "AMGN",
    "AMZN",
    "AVGO",
    "AXP",
    "BA",
    "BAC",
    "BKNG",
    "BLK",
    "CAT",
    "CMCSA",
    "COST",
    "CRM",
    "CSCO",
    "CVX",
    "DIS",
    "GE",
    "GOOGL",
    "GS",
    "HD",
    "HON",
    "IBM",
    "INTC",
    "JNJ",
    "JPM",
    "KO",
    "LIN",
    "LLY",
    "LOW",
    "MA",
    "MCD",
    "META",
    "MRK",
    "MS",
    "MSFT",
    "NFLX",
    "NKE",
    "NVDA",
    "ORCL",
    "PEP",
    "PFE",
    "PG",
    "TMO",
    "TSLA",
    "V",
    "XOM",
)


@lru_cache
def _load_listed_companies(path_str: str) -> dict[str, CompanySeed]:
    path = Path(path_str)
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
    listed = _load_listed_companies(str(LISTED_COMPANIES_PATH))
    if listed:
        return tuple(sorted(listed))
    return DEFAULT_SAMPLE_TICKERS


def catalog_company_count(path: Path | None = None) -> int:
    resolved = path or LISTED_COMPANIES_PATH
    if not resolved.is_file():
        return len(SAMPLE_COMPANIES)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if "company_count" in payload:
        return int(payload["company_count"])
    companies = payload.get("companies", [])
    return len({normalize_cik(str(row["cik"])) for row in companies})


@lru_cache
def _sp500_primary_tickers(path_str: str) -> tuple[str, ...]:
    path = Path(path_str)
    if not path.is_file():
        return DEFAULT_SAMPLE_TICKERS
    payload = json.loads(path.read_text(encoding="utf-8"))
    tickers = payload.get("primary_tickers") or payload.get("tickers") or []
    return tuple(sorted({str(ticker).upper() for ticker in tickers}))


def sp500_primary_tickers(path: Path | None = None) -> tuple[str, ...]:
    resolved = path or SP500_TICKERS_PATH
    return _sp500_primary_tickers(str(resolved))


def sp500_batch_tickers(*, offset: int = 0, limit: int | None = None) -> list[str]:
    tickers = list(sp500_primary_tickers())
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if limit is None:
        return tickers[offset:]
    if limit < 1:
        raise ValueError("limit must be at least 1")
    return tickers[offset : offset + limit]


def get_company_seed(ticker: str) -> CompanySeed:
    normalized_ticker = ticker.upper()
    listed = _load_listed_companies(str(LISTED_COMPANIES_PATH))
    company = listed.get(normalized_ticker) or SAMPLE_COMPANIES.get(normalized_ticker)
    if company is None:
        raise ValueError(f"Unsupported ticker {ticker!r}")
    return CompanySeed(
        ticker=company.ticker,
        cik=normalize_cik(company.cik),
        name=company.name,
        exchange=company.exchange,
    )
