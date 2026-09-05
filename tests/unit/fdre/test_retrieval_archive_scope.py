from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.api.app.db import Base
from apps.api.app.models import Chunk, Company, Document, DocumentElement, Embedding
from fdre.chunking import rebuild_document_chunks
from fdre.indexing.embeddings import FakeEmbeddingProvider, rebuild_embeddings
from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.query import SearchFilters
from fdre.retrieval.sparse import SparseRetriever
from fdre.retrieval.scope import RESEARCH_ARCHIVE_PROFILE


def _seed_online_and_archive_documents(session: Session) -> tuple[Document, Document]:
    company = Company(ticker="TEST", cik="0000000001", name="Scope Test Co.")
    online = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        accession_number="0000000001-26-000001",
    )
    online.elements.append(
        DocumentElement(
            element_type="text",
            section="Risk Factors",
            text="ordinary retrieval risk disclosure",
            reading_order=1,
        )
    )
    archive = Document(
        company=company,
        source_type="sec",
        form_type="10-K",
        accession_number="0000000001-12-000001",
        metadata_json={
            "research_archive": {
                "profile": RESEARCH_ARCHIVE_PROFILE,
                "sections": ["Risk Factors"],
            }
        },
    )
    archive.elements.append(
        DocumentElement(
            element_type="text",
            section="Risk Factors",
            text="archive only risk disclosure",
            reading_order=1,
        )
    )
    session.add(company)
    session.commit()
    return online, archive


def test_archive_document_stays_out_of_generic_chunk_and_embedding_pipeline() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    provider = FakeEmbeddingProvider(dimensions=8)

    with Session(engine) as session:
        online, archive = _seed_online_and_archive_documents(session)

        online_chunks = rebuild_document_chunks(session, online.id, max_tokens=50)
        archive_chunks = rebuild_document_chunks(session, archive.id, max_tokens=50)

        assert len(online_chunks) == 1
        assert archive_chunks == []
        assert session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == archive.id)
        ) == 0

        indexed = rebuild_embeddings(
            session,
            provider,
            tickers=["TEST"],
            missing_only=True,
            batch_size=2,
            concurrency=2,
        )

        assert indexed == 1
        assert session.scalar(select(func.count()).select_from(Embedding)) == 1

    engine.dispose()


def test_accidental_archive_chunks_are_quarantined_from_index_and_retrieval() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    provider = FakeEmbeddingProvider(dimensions=8)

    with Session(engine) as session:
        online, archive = _seed_online_and_archive_documents(session)
        online_chunk = rebuild_document_chunks(session, online.id, max_tokens=50)[0]
        archive_element = session.scalar(
            select(DocumentElement).where(DocumentElement.document_id == archive.id)
        )
        assert archive_element is not None
        accidental_archive_chunk = Chunk(
            document_id=archive.id,
            element_id=archive_element.id,
            chunk_text="archive only risk disclosure",
            chunk_type="text",
            section="Risk Factors",
            token_count=4,
            metadata_json={"ticker": "TEST", "form_type": "10-K"},
        )
        session.add(accidental_archive_chunk)
        session.commit()

        indexed = rebuild_embeddings(
            session,
            provider,
            tickers=["TEST"],
            missing_only=True,
            batch_size=2,
            concurrency=2,
        )
        embedded_chunk_ids = set(session.scalars(select(Embedding.chunk_id)))

        assert indexed == 1
        assert embedded_chunk_ids == {online_chunk.id}
        assert accidental_archive_chunk.id not in embedded_chunk_ids

        # Simulate contamination produced before the scope guard existed. Retrieval
        # must still fail closed even when an archive chunk already has an embedding.
        session.add(
            Embedding(
                chunk_id=accidental_archive_chunk.id,
                provider=provider.name,
                model=provider.model,
                dimensions=provider.dimensions,
                vector=provider.embed_texts([accidental_archive_chunk.chunk_text])[0],
            )
        )
        session.commit()

        filters = SearchFilters()
        dense = DenseRetriever(provider).search(
            session,
            "risk disclosure",
            filters=filters,
            limit=10,
        )
        sparse = SparseRetriever().search(
            session,
            "risk disclosure",
            filters=filters,
            limit=10,
        )

        assert {candidate.chunk_id for candidate in dense} == {online_chunk.id}
        assert {candidate.chunk_id for candidate in sparse} == {online_chunk.id}

    engine.dispose()


def test_embedding_rebuild_pages_large_missing_set_and_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    provider = FakeEmbeddingProvider(dimensions=8)

    with Session(engine) as session:
        company = Company(ticker="PAGE", cik="0000000002", name="Paging Test Co.")
        document = Document(
            company=company,
            source_type="sec",
            form_type="10-K",
            accession_number="0000000002-26-000001",
        )
        document.elements.extend(
            [
                DocumentElement(
                    element_type="text",
                    section="Risk Factors",
                    text=f"unique disclosure number {index}",
                    reading_order=index,
                )
                for index in range(1, 10)
            ]
        )
        session.add(company)
        session.commit()
        chunks = rebuild_document_chunks(session, document.id, max_tokens=50)
        assert len(chunks) == 9

        first = rebuild_embeddings(
            session,
            provider,
            tickers=["PAGE"],
            missing_only=True,
            batch_size=2,
            concurrency=2,
        )
        second = rebuild_embeddings(
            session,
            provider,
            tickers=["PAGE"],
            missing_only=True,
            batch_size=2,
            concurrency=2,
        )

        assert first == 9
        assert second == 0
        assert session.scalar(select(func.count()).select_from(Embedding)) == 9

    engine.dispose()
