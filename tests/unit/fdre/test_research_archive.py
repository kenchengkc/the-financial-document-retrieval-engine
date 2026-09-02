from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import respx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement, Embedding
from apps.api.app.models.historical_universe import Security, UniverseMembership
from fdre.ingestion.sec_client import SECClient, company_submissions_url
from fdre.ingestion.sec_downloader import SECFilingDownloader
from fdre.parsing.html_filing_parser import HtmlFilingParser
from fdre.research.archive import (
    archive_storage_snapshot,
    export_archive_panel,
    ingest_archive_metadata,
    materialize_archive_filings,
    select_archive_issuers,
)

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "data/sample/sec_filing.html"
OBSERVED_AT = datetime(2026, 9, 1, tzinfo=UTC)


def _seed_archive_universe(session: Session) -> Company:
    company = Company(ticker=None, cik="0000320193", name="Historical Apple Inc.")
    security = Security(company_id=1, security_type="common_stock")
    session.add_all(
        [
            company,
            security,
            UniverseMembership(
                universe_code="sp500",
                security=security,
                effective_from=date(2010, 1, 1),
                effective_to=date(2015, 1, 1),
                source="test",
                source_observed_at=OBSERVED_AT,
                source_hash="a" * 64,
                verification_status="verified",
                confidence=1.0,
            ),
        ]
    )
    session.commit()
    return company


def test_archive_issuer_selection_uses_membership_overlap_not_current_ticker() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_archive_universe(session)

        issuers = select_archive_issuers(
            session,
            universe_code="sp500",
            period_from=date(2011, 1, 1),
            period_to=date(2025, 12, 31),
        )

        assert [(issuer.cik, issuer.name) for issuer in issuers] == [
            ("0000320193", "Historical Apple Inc.")
        ]
    engine.dispose()


@respx.mock
def test_archive_records_missing_root_submissions_without_guessing(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    route = respx.get(company_submissions_url("0000320193")).mock(
        return_value=httpx.Response(404)
    )
    client = SECClient(
        user_agent="FDRE tests test@example.com",
        cache_dir=tmp_path / "cache",
        requests_per_second=10,
    )

    with Session(engine) as session:
        _seed_archive_universe(session)
        issuers = select_archive_issuers(
            session,
            universe_code="sp500",
            period_from=date(2010, 1, 1),
            period_to=date(2025, 12, 31),
        )
        metadata = ingest_archive_metadata(
            session,
            client=client,
            issuers=issuers,
            form_types=["10-K"],
            filed_from=date(2010, 1, 1),
            filed_to=date(2025, 12, 31),
        )

        assert route.called
        assert metadata.filings_selected == 0
        assert metadata.documents_created == 0
        assert metadata.issuers_without_submissions == 1
        assert metadata.missing_submission_ciks == ("0000320193",)
        assert session.scalar(select(func.count()).select_from(Document)) == 0

    client.close()
    engine.dispose()


@respx.mock
def test_archive_materializes_only_research_sections_without_embeddings(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    submissions = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-12-000001"],
                "filingDate": ["2012-10-31"],
                "reportDate": ["2012-09-30"],
                "acceptanceDateTime": ["2012-10-31T16:00:00Z"],
                "form": ["10-K"],
                "primaryDocument": ["aapl-20120930.htm"],
                "size": [len(FIXTURE_PATH.read_bytes())],
            }
        }
    }
    respx.get(company_submissions_url("0000320193")).mock(
        return_value=httpx.Response(200, json=submissions)
    )
    filing_url = (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019312000001/aapl-20120930.htm"
    )
    respx.get(filing_url).mock(
        return_value=httpx.Response(200, content=FIXTURE_PATH.read_bytes())
    )
    client = SECClient(
        user_agent="FDRE tests test@example.com",
        cache_dir=tmp_path / "cache",
        requests_per_second=10,
    )

    with Session(engine) as session:
        _seed_archive_universe(session)
        issuers = select_archive_issuers(
            session,
            universe_code="sp500",
            period_from=date(2010, 1, 1),
            period_to=date(2025, 12, 31),
        )
        metadata = ingest_archive_metadata(
            session,
            client=client,
            issuers=issuers,
            form_types=["10-K"],
            filed_from=date(2010, 1, 1),
            filed_to=date(2025, 12, 31),
        )
        before = archive_storage_snapshot(
            session,
            issuers=issuers,
            filed_from=date(2010, 1, 1),
            filed_to=date(2025, 12, 31),
            form_types=["10-K"],
        )
        materialized = materialize_archive_filings(
            session,
            downloader=SECFilingDownloader(client, raw_data_dir=tmp_path / "raw"),
            parser=HtmlFilingParser(),
            issuers=issuers,
            form_types=["10-K"],
            filed_from=date(2010, 1, 1),
            filed_to=date(2025, 12, 31),
        )
        after = archive_storage_snapshot(
            session,
            issuers=issuers,
            filed_from=date(2010, 1, 1),
            filed_to=date(2025, 12, 31),
            form_types=["10-K"],
        )

        assert metadata.documents_created == 1
        assert materialized.parsed_documents == 1
        assert materialized.parsed_elements > 0
        assert before.embeddings == after.embeddings == 0
        assert session.scalar(select(func.count()).select_from(Chunk)) == 0
        assert session.scalar(select(func.count()).select_from(Embedding)) == 0
        sections = set(session.scalars(select(DocumentElement.section)))
        assert sections == {"Risk Factors"}
        document = session.scalar(select(Document))
        assert document is not None
        assert document.available_at is not None
        assert document.available_at.replace(tzinfo=UTC) == datetime(
            2012, 10, 31, 16, 0, tzinfo=UTC
        )
        assert document.local_path is None
        assert document.sha256_hash is not None

        panel_path = tmp_path / "archive.parquet"
        panel = export_archive_panel(
            session,
            issuers=issuers,
            filed_from=date(2010, 1, 1),
            filed_to=date(2025, 12, 31),
            output_path=panel_path,
        )
        assert panel["rows"] == 1
        assert panel_path.is_file()

        replay = materialize_archive_filings(
            session,
            downloader=SECFilingDownloader(client, raw_data_dir=tmp_path / "raw"),
            parser=HtmlFilingParser(),
            issuers=issuers,
            form_types=["10-K"],
            filed_from=date(2010, 1, 1),
            filed_to=date(2025, 12, 31),
        )
        assert replay.already_materialized == 1
        assert replay.downloaded == 0

    client.close()
    engine.dispose()
