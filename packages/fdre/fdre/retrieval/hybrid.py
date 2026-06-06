from __future__ import annotations

from sqlalchemy.orm import Session

from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.query import RetrievalCandidate, SearchFilters
from fdre.retrieval.sparse import SparseRetriever


class HybridRetriever:
    def __init__(
        self,
        dense: DenseRetriever,
        sparse: SparseRetriever,
        *,
        dense_weight: float = 0.5,
        sparse_weight: float = 0.5,
    ) -> None:
        if dense_weight < 0 or sparse_weight < 0 or dense_weight + sparse_weight == 0:
            raise ValueError("retrieval weights must be non-negative and not both zero")
        total = dense_weight + sparse_weight
        self.dense = dense
        self.sparse = sparse
        self.dense_weight = dense_weight / total
        self.sparse_weight = sparse_weight / total

    def search(
        self,
        session: Session,
        query: str,
        *,
        filters: SearchFilters,
        limit: int,
    ) -> list[RetrievalCandidate]:
        candidate_limit = max(limit * 5, 20)
        dense_candidates = self.dense.search(
            session,
            query,
            filters=filters,
            limit=candidate_limit,
        )
        sparse_candidates = self.sparse.search(
            session,
            query,
            filters=filters,
            limit=candidate_limit,
        )
        dense_normalized = _normalized_scores(
            {candidate.chunk_id: candidate.dense_score or 0.0 for candidate in dense_candidates}
        )
        sparse_normalized = _normalized_scores(
            {candidate.chunk_id: candidate.sparse_score or 0.0 for candidate in sparse_candidates}
        )
        merged: dict[int, RetrievalCandidate] = {}
        for candidate in [*dense_candidates, *sparse_candidates]:
            existing = merged.get(candidate.chunk_id)
            if existing is None:
                existing = candidate.model_copy(deep=True)
                merged[candidate.chunk_id] = existing
            if candidate.dense_score is not None:
                existing.dense_score = candidate.dense_score
            if candidate.sparse_score is not None:
                existing.sparse_score = candidate.sparse_score

        for chunk_id, candidate in merged.items():
            candidate.hybrid_score = (
                self.dense_weight * dense_normalized.get(chunk_id, 0.0)
                + self.sparse_weight * sparse_normalized.get(chunk_id, 0.0)
            )
        ranked = sorted(
            merged.values(),
            key=lambda candidate: (-(candidate.hybrid_score or 0.0), candidate.chunk_id),
        )[:limit]
        for rank, candidate in enumerate(ranked, start=1):
            candidate.rank = rank
        return ranked


def _normalized_scores(scores: dict[int, float]) -> dict[int, float]:
    if not scores:
        return {}
    minimum = min(scores.values())
    maximum = max(scores.values())
    if maximum == minimum:
        return dict.fromkeys(scores, 1.0)
    return {
        chunk_id: (score - minimum) / (maximum - minimum)
        for chunk_id, score in scores.items()
    }
