from __future__ import annotations

from sqlalchemy.orm import Session

from fdre.indexing.sparse_index import PostgresFullTextIndexer
from fdre.retrieval.bm25 import BM25Okapi, tokenize
from fdre.retrieval.query import RetrievalCandidate, SearchFilters


class SparseRetriever:
    def __init__(
        self,
        indexer: PostgresFullTextIndexer | None = None,
        *,
        # BM25 re-ranking underperforms ts_rank on the labeled benchmark
        # (data/evals): document frequencies over the small retrieved pool are
        # too noisy without corpus-level IDF, so it is opt-in.
        bm25: bool = False,
        pool_multiplier: int = 4,
    ) -> None:
        self.indexer = indexer or PostgresFullTextIndexer()
        self.bm25 = bm25
        self.pool_multiplier = max(pool_multiplier, 1)

    def search(
        self,
        session: Session,
        query: str,
        *,
        filters: SearchFilters,
        limit: int,
    ) -> list[RetrievalCandidate]:
        # Postgres FTS is the (fast, indexed) candidate generator; BM25 then
        # re-ranks that pool with saturating TF-IDF, which ranks keyword queries
        # better than ts_rank's cover density.
        pool_limit = max(limit * self.pool_multiplier, limit) if self.bm25 else limit
        candidates = [
            RetrievalCandidate(
                chunk_id=hit.chunk.id,
                text=hit.chunk.chunk_text,
                metadata=hit.chunk.metadata_json or {},
                sparse_score=hit.score,
            )
            for hit in self.indexer.search(session, query, filters=filters, limit=pool_limit)
        ]
        if not self.bm25 or len(candidates) <= 1:
            return candidates[:limit]

        model = BM25Okapi([tokenize(candidate.text) for candidate in candidates])
        scores = model.scores(tokenize(query))
        for candidate, score in zip(candidates, scores, strict=True):
            candidate.sparse_score = score
        candidates.sort(
            key=lambda candidate: (-(candidate.sparse_score or 0.0), candidate.chunk_id)
        )
        return candidates[:limit]
