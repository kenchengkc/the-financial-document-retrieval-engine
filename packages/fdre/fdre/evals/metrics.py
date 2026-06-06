from __future__ import annotations

import math
from collections.abc import Sequence


def recall_at_k(ranked_ids: Sequence[int], relevant_ids: set[int], k: int) -> float:
    if not relevant_ids:
        return 0.0
    return len(set(ranked_ids[:k]) & relevant_ids) / len(relevant_ids)


def precision_at_k(ranked_ids: Sequence[int], relevant_ids: set[int], k: int) -> float:
    if k <= 0:
        return 0.0
    return len(set(ranked_ids[:k]) & relevant_ids) / k


def reciprocal_rank(ranked_ids: Sequence[int], relevant_ids: set[int]) -> float:
    for rank, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_ids: Sequence[int], relevant_ids: set[int], k: int) -> float:
    gains = [1.0 if chunk_id in relevant_ids else 0.0 for chunk_id in ranked_ids[:k]]
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal_hits = min(len(relevant_ids), k)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / ideal if ideal else 0.0
