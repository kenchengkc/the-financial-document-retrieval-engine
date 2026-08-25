from __future__ import annotations

from pathlib import Path

import httpx
import respx

from fdre.ingestion.sec_client import SECClient, build_primary_document_url
from fdre.ingestion.sec_downloader import SECFilingDownloader, sha256_bytes


@respx.mock
def test_downloads_hashes_and_skips_unchanged_filing(tmp_path: Path) -> None:
    filing_html = b"<html><body><p>Filing content</p></body></html>"
    url = build_primary_document_url(
        "320193",
        "0000320193-25-000079",
        "aapl-20250927.htm",
    )
    route = respx.get(url).mock(return_value=httpx.Response(200, content=filing_html))
    client = SECClient(
        user_agent="FDRE tests test@example.com",
        cache_dir=tmp_path / "cache",
        requests_per_second=10,
    )
    downloader = SECFilingDownloader(client, raw_data_dir=tmp_path / "raw")

    first = downloader.download(
        cik="320193",
        accession_number="0000320193-25-000079",
        primary_document="aapl-20250927.htm",
    )
    second = downloader.download(
        cik="320193",
        accession_number="0000320193-25-000079",
        primary_document="aapl-20250927.htm",
        expected_sha256=first.sha256_hash,
    )
    client.close()

    assert first.downloaded is True
    assert first.local_path.read_bytes() == filing_html
    assert first.sha256_hash == sha256_bytes(filing_html)
    assert first.local_path.parts[-3:] == (
        "0000320193",
        "0000320193-25-000079",
        "aapl-20250927.htm",
    )
    assert second.downloaded is False
    assert second.sha256_hash == first.sha256_hash
    assert route.call_count == 1
