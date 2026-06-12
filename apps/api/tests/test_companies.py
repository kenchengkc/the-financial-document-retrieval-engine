from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.db import Base, get_db_session
from apps.api.app.main import create_app
from apps.api.app.models import Chunk, Company, Document, DocumentElement
from apps.api.app.services.companies_service import clear_coverage_cache, get_coverage
from fdre.indexing.embeddings import LocalHashEmbeddingProvider, rebuild_embeddings
from fdre.ingestion.ticker_map import _load_listed_companies, _sp500_primary_tickers


@pytest.fixture(autouse=True)
def clear_catalog_cache() -> Generator[None, None, None]:
    _load_listed_companies.cache_clear()
    _sp500_primary_tickers.cache_clear()
    clear_coverage_cache()
    yield
    _load_listed_companies.cache_clear()
    _sp500_primary_tickers.cache_clear()
    clear_coverage_cache()


def _seed_indexed_company(session: Session, *, ticker: str, cik: str, name: str) -> None:
    company = Company(ticker=ticker, cik=cik, name=name, exchange="Nasdaq")
    document = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        accession_number=f"{cik}-25-000001",
    )
    element = DocumentElement(
        document=document,
        element_type="text",
        section="Business",
        text=f"{name} revenue grew year over year.",
        reading_order=1,
    )
    document.chunks.append(
        Chunk(
            element=element,
            chunk_text=element.text or "",
            chunk_type="text",
            section="Business",
            token_count=6,
        )
    )
    session.add(company)
    session.commit()
    rebuild_embeddings(session, LocalHashEmbeddingProvider(dimensions=8))


def test_coverage_reports_catalog_and_indexed_counts(
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
                        "cik": "0001652044",
                        "name": "Alphabet Inc.",
                        "exchange": "Nasdaq",
                        "primary_ticker": "GOOG",
                        "tickers": ["GOOG", "GOOGL"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    sp500_path = tmp_path / "sp500_tickers.json"
    sp500_path.write_text(
        json.dumps({"primary_tickers": ["AAPL", "GOOG"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("fdre.ingestion.ticker_map.LISTED_COMPANIES_PATH", listed_path)
    monkeypatch.setattr("fdre.ingestion.ticker_map.SP500_TICKERS_PATH", sp500_path)

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_indexed_company(
            session,
            ticker="AAPL",
            cik="0000320193",
            name="Apple Inc.",
        )

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_session
    client = TestClient(app)

    response = client.get("/coverage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_count"] == 2
    assert payload["sp500_catalog_count"] == 2
    assert payload["indexed_count"] == 1
    assert payload["sp500_indexed_count"] == 1
    assert payload["indexed_tickers"] == ["AAPL"]
    assert payload["document_count"] == 1
    assert payload["chunk_count"] == 1


def test_companies_endpoint_supports_indexed_only_filter() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(ticker="MSFT", cik="0000789019", name="Microsoft Corporation")
        document = Document(
            company=company,
            source_type="sec",
            form_type="10-K",
            accession_number="0000789019-25-000001",
        )
        session.add(company)
        session.add(document)
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_session
    client = TestClient(app)

    all_response = client.get("/companies")
    indexed_response = client.get("/companies", params={"indexed_only": True})

    assert all_response.status_code == 200
    assert indexed_response.status_code == 200
    assert all_response.json()["total"] == 1
    assert indexed_response.json()["total"] == 0


def test_coverage_reuses_cached_database_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listed_path = tmp_path / "listed_companies.json"
    listed_path.write_text(
        json.dumps(
            {
                "company_count": 1,
                "companies": [
                    {
                        "cik": "0000320193",
                        "name": "Apple Inc.",
                        "exchange": "Nasdaq",
                        "primary_ticker": "AAPL",
                        "tickers": ["AAPL"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    sp500_path = tmp_path / "sp500_tickers.json"
    sp500_path.write_text(
        json.dumps({"primary_tickers": ["AAPL"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("fdre.ingestion.ticker_map.LISTED_COMPANIES_PATH", listed_path)
    monkeypatch.setattr("fdre.ingestion.ticker_map.SP500_TICKERS_PATH", sp500_path)

    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_indexed_company(
            session,
            ticker="AAPL",
            cik="0000320193",
            name="Apple Inc.",
        )

        first = get_coverage(session)
        session.execute(delete(Company))
        session.commit()
        second = get_coverage(session)

    assert first == second
