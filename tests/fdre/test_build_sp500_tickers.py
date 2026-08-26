from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.build_sp500_tickers import build_sp500_tickers, write_sp500_tickers


def test_build_sp500_tickers_maps_symbols_to_catalog_primary_tickers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listed_path = tmp_path / "listed_companies.json"
    listed_path.write_text(
        json.dumps(
            {
                "company_count": 2,
                "companies": [
                    {
                        "cik": "0000320193",
                        "name": "Apple Inc.",
                        "exchange": "Nasdaq",
                        "primary_ticker": "AAPL",
                        "tickers": ["AAPL"],
                    },
                    {
                        "cik": "0000789019",
                        "name": "Microsoft Corporation",
                        "exchange": "Nasdaq",
                        "primary_ticker": "MSFT",
                        "tickers": ["MSFT"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("scripts.build_sp500_tickers.LISTED_COMPANIES_PATH", listed_path)
    monkeypatch.setattr(
        "scripts.build_sp500_tickers._load_wikipedia_symbols",
        lambda **_: ["AAPL", "MSFT", "ZZZZ"],
    )

    payload = build_sp500_tickers(user_agent="FDRE test")
    output = tmp_path / "sp500_tickers.json"
    write_sp500_tickers(output, payload)

    assert payload["primary_ticker_count"] == 2
    assert payload["missing_from_catalog"] == ["ZZZZ"]
    assert payload["primary_tickers"] == ["AAPL", "MSFT"]
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["primary_tickers"] == ["AAPL", "MSFT"]
