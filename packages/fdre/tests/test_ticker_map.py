from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from fdre.ingestion.ticker_map import (
    CompanySeed,
    _load_listed_companies,
    _sp500_primary_tickers,
    catalog_company_count,
    get_company_seed,
    sp500_batch_tickers,
    sp500_primary_tickers,
)


@pytest.fixture(autouse=True)
def clear_listed_company_cache() -> Iterator[None]:
    _load_listed_companies.cache_clear()
    _sp500_primary_tickers.cache_clear()
    yield
    _load_listed_companies.cache_clear()
    _sp500_primary_tickers.cache_clear()


def test_get_company_seed_resolves_dual_class_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "companies": [
            {
                "cik": "0001652044",
                "name": "Alphabet Inc.",
                "exchange": "Nasdaq",
                "primary_ticker": "GOOG",
                "tickers": ["GOOG", "GOOGL"],
            }
        ]
    }
    path = tmp_path / "listed_companies.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("fdre.ingestion.ticker_map.LISTED_COMPANIES_PATH", path)

    goog = get_company_seed("GOOG")
    googl = get_company_seed("GOOGL")

    assert goog == googl
    assert goog == CompanySeed("GOOG", "0001652044", "Alphabet Inc.", "Nasdaq")


def test_get_company_seed_falls_back_to_sample_companies() -> None:
    seed = get_company_seed("AAPL")
    assert seed.ticker == "AAPL"
    assert seed.cik == "0000320193"


def test_catalog_company_count_reads_company_count_field(tmp_path: Path) -> None:
    path = tmp_path / "listed_companies.json"
    path.write_text(json.dumps({"company_count": 42, "companies": []}), encoding="utf-8")
    assert catalog_company_count(path) == 42


def test_sp500_batch_tickers_supports_offset_and_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "sp500_tickers.json"
    path.write_text(json.dumps({"primary_tickers": ["AAPL", "MSFT", "NVDA"]}), encoding="utf-8")
    monkeypatch.setattr("fdre.ingestion.ticker_map.SP500_TICKERS_PATH", path)

    assert sp500_primary_tickers() == ("AAPL", "MSFT", "NVDA")
    assert sp500_batch_tickers(offset=1, limit=1) == ["MSFT"]
