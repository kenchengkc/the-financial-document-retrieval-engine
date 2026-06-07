from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import Chunk, Company, Document, DocumentElement, Embedding
from fdre.indexing.embeddings import EmbeddingProvider, cosine_similarity
from fdre.retrieval.query import RetrievalCandidate, SearchFilters, chunk_matches_filters


class DenseRetriever:
    def __init__(self, provider: EmbeddingProvider) -> None:
        self.provider = provider

    def search(
        self,
        session: Session,
        query: str,
        *,
        filters: SearchFilters,
        limit: int,
    ) -> list[RetrievalCandidate]:
        query_vector = self.provider.embed_texts([query], input_type="query")[0]
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            return self._search_postgres(
                session,
                query_vector,
                filters=filters,
                limit=limit,
            )

        rows = session.execute(
            select(Chunk, Embedding)
            .join(Embedding, Embedding.chunk_id == Chunk.id)
            .where(
                Embedding.provider == self.provider.name,
                Embedding.model == self.provider.model,
            )
        ).all()
        candidates = [
            RetrievalCandidate(
                chunk_id=chunk.id,
                text=chunk.chunk_text,
                metadata=chunk.metadata_json or {},
                dense_score=cosine_similarity(query_vector, embedding.vector),
            )
            for chunk, embedding in rows
            if chunk_matches_filters(chunk, filters)
        ]
        return sorted(
            candidates,
            key=lambda candidate: (-(candidate.dense_score or 0.0), candidate.chunk_id),
        )[:limit]

    def _search_postgres(
        self,
        session: Session,
        query_vector: list[float],
        *,
        filters: SearchFilters,
        limit: int,
    ) -> list[RetrievalCandidate]:
        distance = Embedding.vector.cosine_distance(query_vector).label("distance")
        statement = (
            select(Chunk, distance)
            .join(Embedding, Embedding.chunk_id == Chunk.id)
            .join(Document, Document.id == Chunk.document_id)
            .join(Company, Company.id == Document.company_id)
            .join(DocumentElement, DocumentElement.id == Chunk.element_id)
            .where(
                Embedding.provider == self.provider.name,
                Embedding.model == self.provider.model,
                Embedding.dimensions == self.provider.dimensions,
            )
        )
        if filters.tickers:
            statement = statement.where(Company.ticker.in_(filters.tickers))
        if filters.ciks:
            statement = statement.where(Company.cik.in_(filters.ciks))
        if filters.form_types:
            statement = statement.where(Document.form_type.in_(filters.form_types))
        if filters.filing_date_from:
            statement = statement.where(Document.filing_date >= filters.filing_date_from)
        if filters.filing_date_to:
            statement = statement.where(Document.filing_date <= filters.filing_date_to)
        if filters.sections:
            statement = statement.where(Chunk.section.in_(filters.sections))
        if filters.element_types:
            statement = statement.where(DocumentElement.element_type.in_(filters.element_types))
        if filters.chunk_types:
            statement = statement.where(Chunk.chunk_type.in_(filters.chunk_types))

        rows = session.execute(statement.order_by(distance, Chunk.id).limit(limit)).all()
        return [
            RetrievalCandidate(
                chunk_id=chunk.id,
                text=chunk.chunk_text,
                metadata=chunk.metadata_json or {},
                dense_score=max(-1.0, min(1.0, 1.0 - float(row_distance))),
            )
            for chunk, row_distance in rows
        ]
