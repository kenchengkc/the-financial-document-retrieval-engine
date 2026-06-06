from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement, Embedding
from fdre.indexing.embeddings import LocalHashEmbeddingProvider, rebuild_embeddings
from fdre.indexing.sparse_index import PostgresFullTextIndexer
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


def test_sparse_search_works_offline_and_honors_filters() -> None:
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
