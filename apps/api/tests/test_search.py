from __future__ import annotations

from collections.abc import Generator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import Base, get_db_session
from apps.api.app.main import create_app
from apps.api.app.models import Chunk, Company, Document, DocumentElement
from apps.api.app.services.retrieval_service import search_documents
from fdre.indexing.embeddings import LocalHashEmbeddingProvider, rebuild_embeddings
from fdre.retrieval.hybrid import HybridRetriever
from fdre.retrieval.query import RetrievalCandidate, SearchFilters


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
            primary_document_url=(
                "https://www.sec.gov/Archives/edgar/data/320193/"
                "000032019325000079/aapl-20250927.htm"
            ),
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
                    "accession_number": "0000320193-25-000079",
                    "source_url": document.primary_document_url,
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
    assert payload["results"][0]["metadata"]["source_url"].endswith(
        "/aapl-20250927.htm"
    )
    assert payload["results"][0]["rerank_score"] is not None


def test_search_service_passes_all_preprocessed_rewrites_to_hybrid_fusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    captured: dict[str, Any] = {}

    def capture_search(
        self: HybridRetriever,
        session: Session,
        query: str,
        *,
        filters: SearchFilters,
        limit: int,
        queries: Sequence[str] | None = None,
        timings_ms: dict[str, int] | None = None,
    ) -> list[RetrievalCandidate]:
        captured["query"] = query
        captured["queries"] = list(queries or [])
        captured["filters"] = filters
        captured["limit"] = limit
        if timings_ms is not None:
            timings_ms.update({"embedding": 0, "dense": 0, "sparse": 0, "fusion": 0})
        return []

    monkeypatch.setattr(HybridRetriever, "search", capture_search)
    settings = Settings(
        EMBEDDING_PROVIDER="local_hash",
        EMBEDDING_MODEL="local-hash-v1",
        RERANKER_PROVIDER="fake",
    )

    with Session(engine) as session:
        session.add(Company(ticker="AAPL", cik="0000320193", name="Apple Inc."))
        session.commit()
        result = search_documents(
            session,
            settings,
            query="AAPL risk factors",
            filters=SearchFilters(),
            top_k=5,
        )

    assert len(result.preprocessed.rewritten_queries) > 1
    assert captured["query"] == result.preprocessed.rewritten_queries[0]
    assert captured["queries"] == result.preprocessed.rewritten_queries
    assert captured["filters"] == result.preprocessed.filters
