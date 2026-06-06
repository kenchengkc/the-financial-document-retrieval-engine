from __future__ import annotations

from sqlalchemy.orm import Session

from fdre.indexing.sparse_index import PostgresFullTextIndexer
from fdre.retrieval.query import RetrievalCandidate, SearchFilters


class SparseRetriever:
    def __init__(self, indexer: PostgresFullTextIndexer | None = None) -> None:
        self.indexer = indexer or PostgresFullTextIndexer()

    def search(
        self,
        session: Session,
        query: str,
        *,
        filters: SearchFilters,
        limit: int,
    ) -> list[RetrievalCandidate]:
        return [
            RetrievalCandidate(
                chunk_id=hit.chunk.id,
                text=hit.chunk.chunk_text,
                metadata=hit.chunk.metadata_json or {},
                sparse_score=hit.score,
            )
            for hit in self.indexer.search(
                session,
                query,
                filters=filters,
                limit=limit,
            )
        ]
