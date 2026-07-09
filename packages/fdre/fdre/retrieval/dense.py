from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, SupportsFloat, SupportsIndex, runtime_checkable

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import cast, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement, Select

from apps.api.app.models import Chunk, Company, Document, DocumentElement, Embedding
from fdre.indexing.embeddings import EmbeddingProvider, cosine_similarity
from fdre.retrieval.query import RetrievalCandidate, SearchFilters, chunk_matches_filters

# Higher ef_search improves ANN recall on large issuer corpora (e.g. JPM).
# Lower values keep unfiltered thematic scans closer to the latency gate.
FILTERED_HNSW_EF_SEARCH = 400
UNFILTERED_HNSW_EF_SEARCH = 40

VectorScalar = str | SupportsFloat | SupportsIndex


@runtime_checkable
class SupportsToList(Protocol):
    def to_list(self) -> Iterable[VectorScalar]: ...


@runtime_checkable
class SupportsToListNumpy(Protocol):
    def tolist(self) -> Iterable[VectorScalar]: ...


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
        return self.search_with_vector(
            session, query_vector, filters=filters, limit=limit
        )

    def search_with_vector(
        self,
        session: Session,
        query_vector: list[float],
        *,
        filters: SearchFilters,
        limit: int,
    ) -> list[RetrievalCandidate]:
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
                dense_score=cosine_similarity(
                    query_vector, _as_float_list(embedding.vector)
                ),
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
        use_halfvec = (
            self.provider.name == "voyage"
            and self.provider.model == "voyage-4-large"
            and self.provider.dimensions == 512
        )
        if use_halfvec:
            distance = cast(Embedding.vector, HALFVEC(512)).cosine_distance(
                query_vector
            ).label("distance")
        else:
            distance = Embedding.vector.cosine_distance(query_vector).label("distance")

        ef_search = (
            FILTERED_HNSW_EF_SEARCH if filters.tickers else UNFILTERED_HNSW_EF_SEARCH
        )
        session.execute(text(f"SET LOCAL hnsw.ef_search = {ef_search}"))

        # Unfiltered thematic scans: ANN-first on embeddings, then join metadata.
        # Keeps the HNSW ORDER BY free of multi-table joins.
        if use_halfvec and not filters.tickers:
            return self._search_postgres_ann_first(
                session, distance=distance, filters=filters, limit=limit
            )

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
        statement = _apply_filters(statement, filters)
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

    def _search_postgres_ann_first(
        self,
        session: Session,
        *,
        distance: ColumnElement[float],
        filters: SearchFilters,
        limit: int,
    ) -> list[RetrievalCandidate]:
        oversample = max(limit * 3, limit)
        neighbor_ids = [
            int(row[0])
            for row in session.execute(
                select(Embedding.chunk_id)
                .where(
                    Embedding.provider == self.provider.name,
                    Embedding.model == self.provider.model,
                    Embedding.dimensions == self.provider.dimensions,
                )
                .order_by(distance, Embedding.chunk_id)
                .limit(oversample)
            ).all()
        ]
        if not neighbor_ids:
            return []
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
                Chunk.id.in_(neighbor_ids),
            )
        )
        statement = _apply_filters(statement, filters)
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


def _apply_filters(
    statement: Select[tuple[Chunk, float]],
    filters: SearchFilters,
) -> Select[tuple[Chunk, float]]:
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
    if filters.accepted_at_from:
        statement = statement.where(Document.accepted_at >= filters.accepted_at_from)
    if filters.accepted_at_to:
        statement = statement.where(Document.accepted_at <= filters.accepted_at_to)
    if filters.as_of:
        statement = statement.where(Document.available_at <= filters.as_of)
    if filters.amendment_policy == "exclude":
        statement = statement.where(Document.is_amendment.is_(False))
    elif filters.amendment_policy == "only":
        statement = statement.where(Document.is_amendment.is_(True))
    if filters.sections:
        statement = statement.where(Chunk.section.in_(filters.sections))
    if filters.element_types:
        statement = statement.where(
            DocumentElement.element_type.in_(filters.element_types)
        )
    if filters.chunk_types:
        statement = statement.where(Chunk.chunk_type.in_(filters.chunk_types))
    return statement


def _as_float_list(vector: object) -> list[float]:
    if isinstance(vector, SupportsToList):
        return [float(value) for value in vector.to_list()]
    if isinstance(vector, SupportsToListNumpy):
        return [float(value) for value in vector.tolist()]
    if isinstance(vector, (list, tuple)):
        return [float(value) for value in vector]
    text = str(vector).strip()
    if "HalfVector(" in text:
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            text = text[start + 1 : end]
    elif text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [float(part) for part in text.split(",") if part.strip()]
