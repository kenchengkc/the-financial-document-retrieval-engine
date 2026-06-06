from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import respx
from scripts.download_filings import process_documents
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Company, Document
from fdre.ingestion.sec_client import SECClient
from fdre.ingestion.sec_downloader import SECFilingDownloader


@respx.mock
def test_download_updates_document_path_and_hash(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    company = Company(ticker="AAPL", cik="0000320193", name="Apple Inc.")
    document = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        filing_date=date(2025, 10, 31),
        accession_number="0000320193-25-000079",
        primary_document_url=(
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000032019325000079/aapl-20250927.htm"
        ),
        metadata_json={"primary_document": "aapl-20250927.htm"},
    )
    filing_html = b"<html><body><p>Filing content</p></body></html>"
    route = respx.get(document.primary_document_url).mock(
        return_value=httpx.Response(200, content=filing_html)
    )
    client = SECClient(
        user_agent="FDRE tests test@example.com",
        cache_dir=tmp_path / "cache",
        requests_per_second=10,
    )

    with Session(engine) as session:
        session.add(company)
        session.commit()

        summary = process_documents(
            session,
            downloader=SECFilingDownloader(client, raw_data_dir=tmp_path / "raw"),
            tickers=["AAPL"],
            form_types=["10-K"],
            limit=1,
            download=True,
        )
        stored_document = session.scalar(select(Document))

        assert summary.downloaded == 1
        assert stored_document is not None
        assert stored_document.local_path is not None
        assert Path(stored_document.local_path).is_file()
        assert stored_document.sha256_hash is not None

    client.close()
    assert route.call_count == 1
