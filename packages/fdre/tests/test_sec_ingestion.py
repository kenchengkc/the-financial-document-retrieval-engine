from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx
from scripts.ingest_sec_sample import ingest_sec_metadata
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Company, Document
from fdre.ingestion.sec_client import SECClient, company_submissions_url


@respx.mock
def test_ingestion_inserts_and_updates_companies_and_documents(tmp_path: Path) -> None:
    payload = {
        "name": "Apple Inc.",
        "exchanges": ["Nasdaq"],
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
                "form": ["10-K", "10-Q", "10-K", "10-Q"],
                "primaryDocument": [
                    "aapl-20250927.htm",
                    "aapl-20250628.htm",
                    "aapl-20240928.htm",
                    "aapl-20240629.htm",
                ],
                "size": [100, 90, 80, 70],
            }
        },
    }
    route = respx.get(company_submissions_url("320193")).mock(
        return_value=httpx.Response(200, json=payload)
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    client = SECClient(
        user_agent="FDRE tests test@example.com",
        cache_dir=tmp_path,
        requests_per_second=10,
    )

    with Session(engine) as session:
        created = ingest_sec_metadata(
            session,
            client=client,
            tickers=["AAPL"],
            form_types=["10-K", "10-Q"],
            limit=1,
        )
        updated = ingest_sec_metadata(
            session,
            client=client,
            tickers=["AAPL"],
            form_types=["10-K", "10-Q"],
            limit=1,
        )

        assert created.companies_created == 1
        assert created.documents_created == 2
        assert updated.companies_updated == 1
        assert updated.documents_updated == 2
        assert session.scalar(select(func.count()).select_from(Company)) == 1
        assert session.scalar(select(func.count()).select_from(Document)) == 2
        document = session.scalar(select(Document).where(Document.form_type == "10-K"))
        assert document is not None
        assert document.primary_document_url is not None
        assert document.primary_document_url.endswith("/aapl-20250927.htm")

    client.close()
    assert route.call_count == 1


@respx.mock
def test_ingestion_reuses_company_row_for_dual_class_ticker_alias(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = {
        "name": "Alphabet Inc.",
        "exchanges": ["Nasdaq"],
        "filings": {
            "recent": {
                "accessionNumber": ["0001652044-25-000123"],
                "filingDate": ["2025-10-31"],
                "reportDate": ["2025-09-30"],
                "form": ["10-K"],
                "primaryDocument": ["goog-20250930.htm"],
                "size": [100],
            }
        },
    }
    route = respx.get(company_submissions_url("1652044")).mock(
        return_value=httpx.Response(200, json=payload)
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    client = SECClient(
        user_agent="FDRE tests test@example.com",
        cache_dir=tmp_path,
        requests_per_second=10,
    )
    listed_payload = {
        "companies": [
            {
                "cik": "0001652044",
                "name": "Alphabet Inc.",
                "exchange": "Nasdaq",
                "primary_ticker": "GOOG",
                "tickers": ["GOOG", "GOOGL"],
            }
        ]
    }
    listed_path = tmp_path / "listed_companies.json"
    listed_path.write_text(json.dumps(listed_payload), encoding="utf-8")
    monkeypatch.setattr("fdre.ingestion.ticker_map.LISTED_COMPANIES_PATH", listed_path)
    from fdre.ingestion.ticker_map import _load_listed_companies

    _load_listed_companies.cache_clear()

    with Session(engine) as session:
        session.add(
            Company(
                ticker="GOOGL",
                cik="0001652044",
                name="Alphabet Inc.",
                exchange="Nasdaq",
            )
        )
        session.commit()

        summary = ingest_sec_metadata(
            session,
            client=client,
            tickers=["GOOGL"],
            form_types=["10-K"],
            limit=1,
        )

        company = session.scalar(select(Company))
        assert summary.companies_created == 0
        assert summary.companies_updated == 1
        assert session.scalar(select(func.count()).select_from(Company)) == 1
        assert company is not None
        assert company.ticker == "GOOGL"
        assert company.cik == "0001652044"

    client.close()
    assert route.call_count == 1
    _load_listed_companies.cache_clear()
