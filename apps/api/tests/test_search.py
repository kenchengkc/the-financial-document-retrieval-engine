from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import Base, get_db_session
from apps.api.app.main import create_app
from apps.api.app.models import Chunk, Company, Document, DocumentElement
from fdre.indexing.embeddings import LocalHashEmbeddingProvider, rebuild_embeddings


def test_search_endpoint_returns_ranked_evidence() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        company = Company(ticker="AAPL", cik="0000320193", name="Apple Inc.")
        document = Document(
            company=company,
            source_type="sec",
            form_type="10-K",
            accession_number="0000320193-25-000079",
        )
        element = DocumentElement(
            document=document,
            element_type="text",
            section="Risk Factors",
            text="Supply constraints may affect product availability.",
            reading_order=1,
        )
        document.chunks.append(
            Chunk(
                element=element,
                chunk_text=element.text or "",
                chunk_type="text",
                section=element.section,
                token_count=6,
                metadata_json={
                    "ticker": "AAPL",
                    "cik": "0000320193",
                    "form_type": "10-K",
                    "section": "Risk Factors",
                    "element_type": "text",
                },
            )
        )
        session.add(company)
        session.commit()
        rebuild_embeddings(session, LocalHashEmbeddingProvider())

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        EMBEDDING_PROVIDER="local_hash",
        EMBEDDING_MODEL="local-hash-v1",
        RERANKER_PROVIDER="fake",
    )
    response = TestClient(app).post(
        "/search",
        json={"query": "Apple risk factors supply constraints", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filters"]["tickers"] == ["AAPL"]
    assert payload["filters"]["sections"] == ["Risk Factors"]
    assert payload["results"][0]["metadata"]["ticker"] == "AAPL"
    assert payload["results"][0]["rerank_score"] is not None
