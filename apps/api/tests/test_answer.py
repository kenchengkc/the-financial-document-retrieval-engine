from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import Base, get_db_session
from apps.api.app.main import create_app
from apps.api.app.models import AnswerRun, Chunk, Company, Document, DocumentElement
from fdre.indexing.embeddings import LocalHashEmbeddingProvider, rebuild_embeddings

QUESTION = "What did Apple say about supply constraints?"


def _seeded_engine() -> Engine:
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
                    "company_name": "Apple Inc.",
                    "form_type": "10-K",
                    "section": "Risk Factors",
                    "element_type": "text",
                    "page_number": 1,
                },
            )
        )
        session.add(company)
        session.commit()
        rebuild_embeddings(session, LocalHashEmbeddingProvider())
    return engine


def _client(engine: Engine, cache_ttl: int = 21600) -> TestClient:
    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    settings = Settings(
        EMBEDDING_PROVIDER="local_hash",
        EMBEDDING_MODEL="local-hash-v1",
        RERANKER_PROVIDER="fake",
        MIN_EVIDENCE_CHUNKS=1,
        MIN_RETRIEVAL_SCORE=0,
        ANSWER_CACHE_TTL_SECONDS=cache_ttl,
    )
    app = create_app()
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def test_answer_endpoint_returns_and_persists_auditable_answer() -> None:
    engine = _seeded_engine()
    response = _client(engine).post("/answer", json={"question": QUESTION})

    assert response.status_code == 200
    payload = response.json()
    assert payload["abstained"] is False
    assert payload["answer"]
    assert payload["citations"][0]["metadata"]["ticker"] == "AAPL"
    assert payload["evidence"][0]["rerank_score"] is not None
    expected_confidence = round(
        0.6 * payload["retrieval_gate"]["max_score"]
        + 0.4 * payload["citations"][0]["confidence"],
        4,
    )
    assert payload["confidence"] == pytest.approx(expected_confidence)
    assert payload["retrieval_gate"]["confidence"] == pytest.approx(expected_confidence)
    assert payload["retrieval_gate"]["confidence_components"]["weights"] == {
        "top_rerank": 0.6,
        "citation_overlap": 0.4,
    }
    assert payload["trace"][-1]["node"] == "finalize_or_abstain"
    with Session(engine) as session:
        run = session.scalar(select(AnswerRun))
        assert run is not None
        assert run.answer_text == payload["answer"]
        assert len(run.citations) == 1


def test_repeat_question_is_served_from_cache() -> None:
    engine = _seeded_engine()
    client = _client(engine)

    first = client.post("/answer", json={"question": QUESTION})
    second = client.post("/answer", json={"question": f"  {QUESTION}  "})  # whitespace-insensitive

    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert first.json() == second.json()
    with Session(engine) as session:
        # the cache hit must not have re-run the pipeline
        assert len(session.scalars(select(AnswerRun)).all()) == 1


def test_cache_disabled_when_ttl_zero() -> None:
    engine = _seeded_engine()
    client = _client(engine, cache_ttl=0)

    first = client.post("/answer", json={"question": QUESTION})
    second = client.post("/answer", json={"question": QUESTION})

    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "MISS"
    with Session(engine) as session:
        assert len(session.scalars(select(AnswerRun)).all()) == 2
