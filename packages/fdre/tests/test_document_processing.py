from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import respx
from scripts.download_filings import process_documents
from scripts.retrieval_pipeline import seed_demo_document
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement, Embedding
from fdre.indexing.embeddings import LocalHashEmbeddingProvider
from fdre.ingestion.sec_client import SECClient
from fdre.ingestion.sec_downloader import SECFilingDownloader
from fdre.parsing.html_filing_parser import HtmlFilingParser

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "data/sample/sec_filing.html"


@respx.mock
def test_download_and_parse_updates_document_rows(tmp_path: Path) -> None:
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
    filing_html = FIXTURE_PATH.read_bytes()
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
            parser=HtmlFilingParser(),
            tickers=["AAPL"],
            form_types=["10-K"],
            limit=1,
            download=True,
            parse=True,
        )
        stored_document = session.scalar(select(Document))

        assert summary.downloaded == 1
        assert summary.parsed_documents == 1
        assert summary.parsed_elements > 0
        assert stored_document is not None
        assert stored_document.local_path is not None
        assert Path(stored_document.local_path).is_file()
        assert stored_document.sha256_hash is not None
        assert session.scalar(select(func.count()).select_from(DocumentElement)) == (
            summary.parsed_elements
        )
        assert session.scalar(
            select(func.count())
            .select_from(DocumentElement)
            .where(DocumentElement.element_type == "table")
        ) == 1

    client.close()
    assert route.call_count == 1


def test_seed_demo_document_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        provider = LocalHashEmbeddingProvider()
        first = seed_demo_document(session, fixture_path=FIXTURE_PATH, provider=provider)
        first_chunk_ids = list(session.scalars(select(Chunk.id).order_by(Chunk.id)))
        second = seed_demo_document(session, fixture_path=FIXTURE_PATH, provider=provider)
        second_chunk_ids = list(session.scalars(select(Chunk.id).order_by(Chunk.id)))

        assert first == second
        assert first_chunk_ids == second_chunk_ids
        assert first["documents"] == 1
        assert first["chunks"] > 0
        assert session.scalar(select(func.count()).select_from(Company)) == 1
        assert session.scalar(select(func.count()).select_from(Document)) == 1
        assert session.scalar(select(func.count()).select_from(Chunk)) == first["chunks"]
        assert session.scalar(select(func.count()).select_from(Embedding)) == first["embeddings"]
