from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from fdre.ingestion.sec_client import (
    RateLimiter,
    SECClient,
    build_primary_document_url,
    company_submissions_url,
    extract_recent_filings,
    normalize_accession,
    normalize_cik,
)


def submissions_payload() -> dict[str, object]:
    return {
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-25-000079",
                    "0000320193-25-000057",
                    "0000320193-24-000123",
                    "0000320193-24-000081",
                ],
                "filingDate": ["2025-10-31", "2025-08-01", "2024-11-01", "2024-08-02"],
                "reportDate": ["2025-09-27", "2025-06-28", "2024-09-28", "2024-06-29"],
                "acceptanceDateTime": [
                    "2025-10-31T06:01:26.000Z",
                    "2025-08-01T06:00:42.000Z",
                    "2024-11-01T06:01:36.000Z",
                    "2024-08-02T06:01:42.000Z",
                ],
                "form": ["10-K", "10-Q", "10-K", "10-Q"],
                "primaryDocument": [
                    "aapl-20250927.htm",
                    "aapl-20250628.htm",
                    "aapl-20240928.htm",
                    "aapl-20240629.htm",
                ],
                "isXBRL": [1, 1, 1, 1],
                "isInlineXBRL": [1, 1, 1, 1],
            }
        },
    }


def test_normalizes_sec_identifiers_and_builds_archive_url() -> None:
    assert normalize_cik("320193") == "0000320193"
    assert normalize_accession("0000320193-25-000079") == "000032019325000079"
    assert build_primary_document_url(
        "320193",
        "0000320193-25-000079",
        "aapl-20250927.htm",
    ) == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019325000079/aapl-20250927.htm"
    )

    with pytest.raises(ValueError):
        normalize_cik("")
    with pytest.raises(ValueError):
        build_primary_document_url("320193", "123", "../filing.htm")
    with pytest.raises(ValueError, match="placeholder"):
        SECClient(user_agent="FDRE local contact@example.com")


def test_rate_limiter_waits_between_network_requests() -> None:
    now = [10.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(
        5,
        clock=lambda: now[0],
        sleep=sleep,
    )
    limiter.wait()
    now[0] += 0.05
    limiter.wait()

    assert sleeps == pytest.approx([0.15])


@respx.mock
def test_lists_latest_filings_per_form_and_reuses_cache(tmp_path: Path) -> None:
    url = company_submissions_url("320193")
    route = respx.get(url).mock(return_value=httpx.Response(200, json=submissions_payload()))
    client = SECClient(
        user_agent="FDRE tests test@example.com",
        cache_dir=tmp_path,
        requests_per_second=10,
    )

    first = client.list_recent_filings("320193", ["10-K", "10-Q"], limit=1)
    second = client.list_recent_filings("320193", ["10-K", "10-Q"], limit=1)
    client.close()

    assert [filing["form_type"] for filing in first] == ["10-K", "10-Q"]
    assert first == second
    assert route.call_count == 1
    assert route.calls[0].request.headers["user-agent"] == "FDRE tests test@example.com"
    cache_files = list(tmp_path.iterdir())
    assert len(cache_files) == 1
    assert json.loads(cache_files[0].read_text())["name"] == "Apple Inc."


def test_extract_recent_filings_supports_form_specific_depth() -> None:
    results = extract_recent_filings(
        submissions_payload(),
        ["10-K", "10-Q"],
        {"10-K": 1, "10-Q": 2},
    )
    assert [filing["form_type"] for filing in results] == ["10-K", "10-Q", "10-Q"]
