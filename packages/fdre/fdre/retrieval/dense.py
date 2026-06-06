from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import Chunk, Embedding
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
        query_vector = self.provider.embed_texts([query])[0]
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
                dense_score=cosine_similarity(query_vector, embedding.vector_json),
            )
            for chunk, embedding in rows
            if chunk_matches_filters(chunk, filters)
        ]
        return sorted(
            candidates,
            key=lambda candidate: (-(candidate.dense_score or 0.0), candidate.chunk_id),
        )[:limit]
