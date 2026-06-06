from __future__ import annotations

from dataclasses import dataclass

from fdre.ingestion.sec_client import normalize_cik


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


def get_company_seed(ticker: str) -> CompanySeed:
    normalized_ticker = ticker.upper()
    try:
        company = SAMPLE_COMPANIES[normalized_ticker]
    except KeyError as error:
        supported = ", ".join(DEFAULT_SAMPLE_TICKERS)
        raise ValueError(f"Unsupported ticker {ticker!r}; choose from {supported}") from error
    return CompanySeed(
        ticker=company.ticker,
        cik=normalize_cik(company.cik),
        name=company.name,
        exchange=company.exchange,
    )
