from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Literal

from sqlalchemy.orm import Session

from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.query import RetrievalCandidate, SearchFilters
from fdre.retrieval.sparse import SparseRetriever

DEFAULT_RRF_K = 60

FusionMethod = Literal["rrf", "weighted"]


def reciprocal_rank_fusion(
    rankings: Sequence[tuple[float, Sequence[int]]],
    *,
    k: int = DEFAULT_RRF_K,
) -> dict[int, float]:
    """Reciprocal Rank Fusion over several ranked id lists.

    Each ranking is ``(weight, [id_by_descending_relevance])`` and contributes
    ``weight / (k + rank)`` to every id it ranks. RRF is rank-based, so it fuses
    lists with incomparable score scales (dense cosine vs BM25 vs lexical) and
    multiple query rewrites without per-list score normalization.
    """
    scores: dict[int, float] = defaultdict(float)
    for weight, ordered_ids in rankings:
        for rank, identifier in enumerate(ordered_ids, start=1):
            scores[identifier] += weight / (k + rank)
    return dict(scores)


class HybridRetriever:
    def __init__(
        self,
        dense: DenseRetriever,
        sparse: SparseRetriever,
        *,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
        # Weighted fusion wins on the labeled benchmark (data/evals): with strong
        # dense embeddings + only two base rankers, preserving the dense score
        # beats RRF's rank-only flattening. RRF stays available for cases with
        # many heterogeneous rankers.
        fusion: FusionMethod = "weighted",
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        if dense_weight < 0 or sparse_weight < 0 or dense_weight + sparse_weight == 0:
            raise ValueError("retrieval weights must be non-negative and not both zero")
        self.dense = dense
        self.sparse = sparse
        self.fusion = fusion
        self.rrf_k = rrf_k
        if fusion == "weighted":
            total = dense_weight + sparse_weight
            self.dense_weight = dense_weight / total
            self.sparse_weight = sparse_weight / total
        else:
            self.dense_weight = dense_weight
            self.sparse_weight = sparse_weight

    def search(
        self,
        session: Session,
        query: str,
        *,
        filters: SearchFilters,
        limit: int,
        queries: Sequence[str] | None = None,
    ) -> list[RetrievalCandidate]:
        # De-duplicate the primary query with any expansion variants; each variant
        # contributes its own dense and sparse ranking to the fusion.
        variants = list(dict.fromkeys([query, *(queries or [])]))
        candidate_limit = max(limit * 5, 20)
        store: dict[int, RetrievalCandidate] = {}
        rankings: list[tuple[float, list[int]]] = []
        for variant in variants:
            dense_candidates = self.dense.search(
                session, variant, filters=filters, limit=candidate_limit
            )
            sparse_candidates = self.sparse.search(
                session, variant, filters=filters, limit=candidate_limit
            )
            for candidate in (*dense_candidates, *sparse_candidates):
                _merge_into_store(store, candidate)
            rankings.append((self.dense_weight, [c.chunk_id for c in dense_candidates]))
            rankings.append((self.sparse_weight, [c.chunk_id for c in sparse_candidates]))

        if self.fusion == "weighted":
            self._score_weighted(store, rankings)
        else:
            for chunk_id, score in reciprocal_rank_fusion(rankings, k=self.rrf_k).items():
                store[chunk_id].hybrid_score = score

        ranked = sorted(
            store.values(),
            key=lambda candidate: (-(candidate.hybrid_score or 0.0), candidate.chunk_id),
        )[:limit]
        for rank, candidate in enumerate(ranked, start=1):
            candidate.rank = rank
        return ranked

    def _score_weighted(
        self,
        store: dict[int, RetrievalCandidate],
        rankings: list[tuple[float, list[int]]],
    ) -> None:
        dense_normalized = _normalized_scores(
            {cid: store[cid].dense_score or 0.0 for cid in store if store[cid].dense_score}
        )
        sparse_normalized = _normalized_scores(
            {cid: store[cid].sparse_score or 0.0 for cid in store if store[cid].sparse_score}
        )
        for chunk_id, candidate in store.items():
            candidate.hybrid_score = self.dense_weight * dense_normalized.get(
                chunk_id, 0.0
            ) + self.sparse_weight * sparse_normalized.get(chunk_id, 0.0)


def _merge_into_store(store: dict[int, RetrievalCandidate], candidate: RetrievalCandidate) -> None:
    existing = store.get(candidate.chunk_id)
    if existing is None:
        store[candidate.chunk_id] = candidate.model_copy(deep=True)
        return
    if candidate.dense_score is not None:
        existing.dense_score = (
            candidate.dense_score
            if existing.dense_score is None
            else max(existing.dense_score, candidate.dense_score)
        )
    if candidate.sparse_score is not None:
        existing.sparse_score = (
            candidate.sparse_score
            if existing.sparse_score is None
            else max(existing.sparse_score, candidate.sparse_score)
        )


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
