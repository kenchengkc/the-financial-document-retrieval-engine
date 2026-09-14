from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from scripts.ingestion.download_filings import process_documents
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Company, Document
from fdre.ingestion.sec_downloader import sha256_bytes
from fdre.ingestion.sec_replay_bundle import (
    build_sec_replay_bundle,
    sec_replay_bundle_sha256,
    verify_sec_replay_bundle,
)
from fdre.parsing.html_filing_parser import HtmlFilingParser

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "data/sample/sec_filing.html"
ACCESSION = "0000320193-25-000079"


def _seed_local_filing(session: Session, raw_path: Path) -> Document:
    raw_bytes = FIXTURE_PATH.read_bytes()
    raw_path.write_bytes(raw_bytes)
    company = Company(ticker="AAPL", cik="0000320193", name="Apple Inc.")
    document = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        filing_date=date(2025, 10, 31),
        accession_number=ACCESSION,
        primary_document_url="https://www.sec.gov/example/aapl-20250927.htm",
        local_path=str(raw_path),
        sha256_hash=sha256_bytes(raw_bytes),
        metadata_json={"primary_document": "aapl-20250927.htm"},
    )
    session.add(company)
    session.commit()
    return document


def test_sec_replay_bundle_is_deterministic_and_offline_portable(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    raw_path = tmp_path / "aapl-20250927.htm"
    first_bundle = tmp_path / "first.zip"
    second_bundle = tmp_path / "second.zip"

    with Session(engine) as session:
        _seed_local_filing(session, raw_path)
        summary = process_documents(
            session,
            downloader=None,
            parser=HtmlFilingParser(),
            tickers=["AAPL"],
            form_types=["10-K"],
            limit=1,
            download=False,
            parse=True,
        )
        assert summary.parsed_documents == 1

        first = build_sec_replay_bundle(
            session,
            accession_numbers=[ACCESSION],
            destination=first_bundle,
        )
        second = build_sec_replay_bundle(
            session,
            accession_numbers=[ACCESSION],
            destination=second_bundle,
        )

    assert first == second
    assert sec_replay_bundle_sha256(first_bundle) == sec_replay_bundle_sha256(second_bundle)

    raw_path.unlink()
    verified = verify_sec_replay_bundle(first_bundle)
    assert verified == first
    assert verified.entries[0].accession_number == ACCESSION


def test_sec_replay_bundle_rejects_legacy_document_without_parse_provenance(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    raw_path = tmp_path / "legacy.htm"

    with Session(engine) as session:
        _seed_local_filing(session, raw_path)
        with pytest.raises(ValueError, match="cannot be upgraded by redownloading"):
            build_sec_replay_bundle(
                session,
                accession_numbers=[ACCESSION],
                destination=tmp_path / "legacy.zip",
            )
