from __future__ import annotations

from typing import Any, Literal

import pytest
from scripts.build_listed_company_seeds import _looks_like_etf, build_listed_companies


def test_looks_like_etf_filters_funds_and_etns() -> None:
    assert _looks_like_etf("SPDR S&P 500 ETF TRUST")
    assert _looks_like_etf("ProShares Ultra Semiconductors")
    assert not _looks_like_etf("Apple Inc.")


def test_build_listed_companies_deduplicates_by_cik(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        @property
        def text(self) -> str:
            return (
                "Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|"
                "ETF|Round Lot Size|Test Issue|Financial Status|CQS Symbol|"
                "NASDAQ Symbol|NextShares\n"
                "Y|GOOG|Alphabet Inc.|Q| |N|100|N||GOOG|GOOG|N\n"
                "Y|GOOGL|Alphabet Inc.|Q| |N|100|N||GOOGL|GOOGL|N\n"
                "Y|SPY|SPDR S&P 500 ETF TRUST|N| |Y|100|N||SPY|SPY|N\n"
            )

        def json(self) -> dict[str, Any]:
            return {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [1652044, "Alphabet Inc.", "GOOGL", "Nasdaq"],
                    [1652044, "Alphabet Inc.", "GOOG", "Nasdaq"],
                    [884394, "SPDR S&P 500 ETF TRUST", "SPY", "NYSE"],
                ],
            }

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *args: Any) -> Literal[False]:
            return False

        def get(self, url: str, headers: dict[str, str] | None = None) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("scripts.build_listed_company_seeds.httpx.Client", FakeClient)
    companies = build_listed_companies(user_agent="FDRE tests test@example.com")

    assert len(companies) == 1
    assert companies[0].primary_ticker == "GOOG"
    assert companies[0].tickers == ("GOOG", "GOOGL")
