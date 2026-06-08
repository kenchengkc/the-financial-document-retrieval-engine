from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdre.ingestion.ticker_map import (
    CompanySeed,
    _load_listed_companies,
    get_company_seed,
)


@pytest.fixture(autouse=True)
def clear_listed_company_cache() -> None:
    _load_listed_companies.cache_clear()
    yield
    _load_listed_companies.cache_clear()


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
