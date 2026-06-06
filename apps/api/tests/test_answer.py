from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import Base, get_db_session
from apps.api.app.main import create_app
from apps.api.app.models import AnswerRun, Chunk, Company, Document, DocumentElement
from fdre.indexing.embeddings import LocalHashEmbeddingProvider, rebuild_embeddings


def test_answer_endpoint_returns_and_persists_auditable_answer() -> None:
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

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        EMBEDDING_PROVIDER="local_hash",
        EMBEDDING_MODEL="local-hash-v1",
        RERANKER_PROVIDER="fake",
        MIN_EVIDENCE_CHUNKS=1,
        MIN_RETRIEVAL_SCORE=0,
    )
    response = TestClient(app).post(
        "/answer",
        json={"question": "What did Apple say about supply constraints?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["abstained"] is False
    assert payload["answer"]
    assert payload["citations"][0]["metadata"]["ticker"] == "AAPL"
    assert payload["evidence"][0]["rerank_score"] is not None
    assert payload["trace"][-1]["node"] == "finalize_or_abstain"
    with Session(engine) as session:
        run = session.scalar(select(AnswerRun))
        assert run is not None
        assert run.answer_text == payload["answer"]
        assert len(run.citations) == 1
