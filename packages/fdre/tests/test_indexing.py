from __future__ import annotations

import time

import respx
from httpx import Response
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement, Embedding
from fdre.indexing.embeddings import (
    EmbeddingRateLimiter,
    LocalHashEmbeddingProvider,
    VoyageEmbeddingProvider,
    _chunk_select_statement,
    rebuild_embeddings,
)
from fdre.indexing.sparse_index import PostgresFullTextIndexer, build_sparse_tsquery
from fdre.retrieval.query import SearchFilters


def _seed_chunk(session: Session) -> Chunk:
    company = Company(ticker="NVDA", cik="0001045810", name="NVIDIA Corporation")
    document = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        accession_number="0001045810-25-000023",
    )
    element = DocumentElement(
        document=document,
        element_type="text",
        section="Business",
        text="Data center revenue grew on strong AI demand.",
        reading_order=1,
    )
    chunk = Chunk(
        document=document,
        element=element,
        chunk_text="Data center revenue grew on strong AI demand.",
        chunk_type="text",
        section="Business",
        token_count=9,
        metadata_json={
            "ticker": "NVDA",
            "cik": "0001045810",
            "form_type": "10-K",
            "section": "Business",
            "element_type": "text",
        },
    )
    session.add(company)
    session.commit()
    return chunk


def test_local_embeddings_are_deterministic_and_persisted() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    provider = LocalHashEmbeddingProvider(dimensions=16)
    assert provider.embed_texts(["revenue"]) == provider.embed_texts(["revenue"])

    with Session(engine) as session:
        chunk = _seed_chunk(session)
        assert rebuild_embeddings(session, provider) == 1
        embedding = session.scalar(select(Embedding))
        assert embedding is not None
        assert embedding.chunk_id == chunk.id
        assert embedding.dimensions == 16


def test_incremental_indexing_preserves_existing_embeddings() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    provider = LocalHashEmbeddingProvider(dimensions=16)

    with Session(engine) as session:
        _seed_chunk(session)
        assert rebuild_embeddings(session, provider, missing_only=True) == 1
        embedding_id = session.scalar(select(Embedding.id))

        assert rebuild_embeddings(session, provider, missing_only=True) == 0
        assert session.scalar(select(Embedding.id)) == embedding_id


def test_incremental_indexing_replaces_wrong_dimensions() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        _seed_chunk(session)
        assert rebuild_embeddings(
            session,
            LocalHashEmbeddingProvider(dimensions=8),
            missing_only=True,
        ) == 1
        assert rebuild_embeddings(
            session,
            LocalHashEmbeddingProvider(dimensions=16),
            missing_only=True,
        ) == 1
        embeddings = list(session.scalars(select(Embedding)))
        assert len(embeddings) == 1
        assert embeddings[0].dimensions == 16


def test_missing_embedding_query_uses_correlated_exists() -> None:
    provider = LocalHashEmbeddingProvider(dimensions=16)

    statement = _chunk_select_statement(
        chunk_ids=None,
        document_ids=None,
        tickers=["AAPL"],
        missing_only=True,
        provider=provider,
    )
    compiled = str(
        statement.compile(
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "EXISTS" in compiled
    assert "embeddings.chunk_id = chunks.id" in compiled
    assert "NOT IN" not in compiled


@respx.mock
def test_voyage_provider_retries_after_rate_limit() -> None:
    route = respx.post("https://api.voyageai.com/v1/embeddings")
    route.side_effect = [
        Response(429, headers={"Retry-After": "0"}),
        Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]},
        ),
    ]
    provider = VoyageEmbeddingProvider(
        api_key="test-key",
        model="voyage-4-large",
        dimensions=2,
        requests_per_minute=None,
        tokens_per_minute=None,
    )

    assert provider.embed_texts(["hello"]) == [[1.0, 0.0]]
    assert route.call_count == 2


@respx.mock
def test_voyage_provider_uses_retrieval_input_type_and_dimensions() -> None:
    route = respx.post("https://api.voyageai.com/v1/embeddings").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )
    )
    provider = VoyageEmbeddingProvider(
        api_key="test-key",
        model="voyage-4-large",
        dimensions=2,
        requests_per_minute=None,
        tokens_per_minute=None,
    )

    assert provider.embed_texts(["first", "second"], input_type="query") == [
        [1.0, 0.0],
        [0.0, 1.0],
    ]
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-key"
    assert b'"input_type":"query"' in request.content
    assert b'"output_dimension":2' in request.content


def test_rebuild_embeddings_can_scope_to_tickers() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    provider = LocalHashEmbeddingProvider(dimensions=16)

    with Session(engine) as session:
        nvda_chunk = _seed_chunk(session)
        aapl_company = Company(ticker="AAPL", cik="0000320193", name="Apple Inc.")
        aapl_document = Document(
            company=aapl_company,
            source_type="sec",
            form_type="10-K",
            accession_number="0000320193-25-000079",
        )
        aapl_element = DocumentElement(
            document=aapl_document,
            element_type="text",
            section="Business",
            text="Apple sells hardware and services worldwide.",
            reading_order=1,
        )
        aapl_chunk = Chunk(
            document=aapl_document,
            element=aapl_element,
            chunk_text="Apple sells hardware and services worldwide.",
            chunk_type="text",
            section="Business",
            token_count=7,
        )
        session.add(aapl_company)
        session.commit()

        assert rebuild_embeddings(session, provider, tickers=["NVDA"]) == 1
        embedded_ids = set(session.scalars(select(Embedding.chunk_id)))
        assert embedded_ids == {nvda_chunk.id}
        assert aapl_chunk.id not in embedded_ids


def test_rebuild_embeddings_runs_concurrently_for_local_provider() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    provider = LocalHashEmbeddingProvider(dimensions=16)

    with Session(engine) as session:
        company = Company(ticker="NVDA", cik="0001045810", name="NVIDIA Corporation")
        document = Document(
            company=company,
            source_type="sec",
            form_type="10-K",
            accession_number="0001045810-25-000024",
        )
        session.add(company)
        for index in range(4):
            element = DocumentElement(
                document=document,
                element_type="text",
                section="Business",
                text=f"Chunk number {index} about AI demand.",
                reading_order=index,
            )
            session.add(
                Chunk(
                    document=document,
                    element=element,
                    chunk_text=element.text or "",
                    chunk_type="text",
                    section="Business",
                    token_count=6,
                )
            )
        session.commit()

        assert rebuild_embeddings(session, provider, batch_size=1, concurrency=4) == 4


def test_embedding_rate_limiter_enforces_token_budget() -> None:
    limiter = EmbeddingRateLimiter(requests_per_minute=None, tokens_per_minute=10)
    start = time.monotonic()
    limiter.acquire(token_count=6)
    limiter.acquire(token_count=6)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.5


def test_sparse_search_works_offline_and_honors_filters() -> None:
    assert build_sparse_tsquery("AI revenue, AI demand") == "ai | revenue | demand"
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_chunk(session)
        indexer = PostgresFullTextIndexer()
        hits = indexer.search(
            session,
            "AI revenue",
            filters=SearchFilters(tickers=["NVDA"]),
            limit=5,
        )
        assert len(hits) == 1
        assert hits[0].score > 0
        assert (
            indexer.search(
                session,
                "AI revenue",
                filters=SearchFilters(tickers=["AAPL"]),
                limit=5,
            )
            == []
        )
