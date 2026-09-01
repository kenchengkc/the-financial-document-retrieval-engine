from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from fdre.ingestion.sec_client import (
    RateLimiter,
    SECClient,
    build_primary_document_url,
    company_facts_url,
    company_submissions_url,
    extract_filings,
    extract_recent_filings,
    normalize_accession,
    normalize_cik,
    submissions_history_file_url,
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
    assert company_facts_url("320193").endswith("/CIK0000320193.json")

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


def test_extract_filings_merges_paginated_history_and_filters_dates() -> None:
    historical = {
        "accessionNumber": ["0000320193-12-000001", "0000320193-11-000001"],
        "filingDate": ["2012-10-31", "2011-10-31"],
        "reportDate": ["2012-09-30", "2011-09-30"],
        "acceptanceDateTime": ["2012-10-31T16:00:00Z", "2011-10-31T16:00:00Z"],
        "form": ["10-K", "10-K"],
        "primaryDocument": ["aapl-20120930.htm", "aapl-20110930.htm"],
    }

    results = extract_filings(
        [submissions_payload(), historical],
        ["10-K"],
        filed_from=date(2012, 1, 1),
        filed_to=date(2024, 12, 31),
    )

    assert [filing["accession_number"] for filing in results] == [
        "0000320193-24-000123",
        "0000320193-12-000001",
    ]


@respx.mock
def test_company_filing_history_loads_declared_sec_pages(tmp_path: Path) -> None:
    root = submissions_payload()
    root["filings"]["files"] = [{"name": "CIK0000320193-submissions-001.json"}]  # type: ignore[index]
    historical = {
        "accessionNumber": ["0000320193-12-000001"],
        "filingDate": ["2012-10-31"],
        "reportDate": ["2012-09-30"],
        "form": ["10-K"],
        "primaryDocument": ["aapl-20120930.htm"],
    }
    root_route = respx.get(company_submissions_url("320193")).mock(
        return_value=httpx.Response(200, json=root)
    )
    history_route = respx.get(
        submissions_history_file_url("CIK0000320193-submissions-001.json")
    ).mock(return_value=httpx.Response(200, json=historical))
    client = SECClient(
        user_agent="FDRE tests test@example.com",
        cache_dir=tmp_path,
        requests_per_second=10,
    )

    results = client.list_filings(
        "320193",
        ["10-K"],
        filed_from=date(2012, 1, 1),
        filed_to=date(2012, 12, 31),
    )
    client.close()

    assert [filing["accession_number"] for filing in results] == [
        "0000320193-12-000001"
    ]
    assert root_route.call_count == 1
    assert history_route.call_count == 1


def test_submissions_history_file_url_rejects_paths() -> None:
    with pytest.raises(ValueError):
        submissions_history_file_url("../history.json")


@respx.mock
def test_sec_client_retries_transient_forbidden_response(tmp_path: Path) -> None:
    sleeps: list[float] = []
    route = respx.get(company_submissions_url("320193")).mock(
        side_effect=[
            httpx.Response(403),
            httpx.Response(200, json=submissions_payload()),
        ]
    )
    client = SECClient(
        user_agent="FDRE tests test@example.com",
        cache_dir=tmp_path,
        requests_per_second=10,
        retry_backoff_seconds=0.25,
        retry_sleep=sleeps.append,
    )

    payload = client.get_company_submissions("320193")
    client.close()

    assert payload["name"] == "Apple Inc."
    assert route.call_count == 2
    assert sleeps == [0.25]
