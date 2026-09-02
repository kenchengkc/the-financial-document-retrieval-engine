from __future__ import annotations

import json

from fdre.ingestion import ticker_map


def test_default_catalog_paths_resolve_checked_in_repository_data() -> None:
    assert ticker_map.LISTED_COMPANIES_PATH.is_file()
    assert ticker_map.SP500_TICKERS_PATH.is_file()

    payload = json.loads(ticker_map.SP500_TICKERS_PATH.read_text(encoding="utf-8"))
    primary_tickers = set(ticker_map.sp500_primary_tickers())

    assert len(primary_tickers) == payload["primary_ticker_count"]
    assert len(primary_tickers) > 400
    assert {"ARE", "MET", "AEP", "BX", "SO"}.issubset(primary_tickers)
    assert ticker_map.catalog_company_count() > 5_000
