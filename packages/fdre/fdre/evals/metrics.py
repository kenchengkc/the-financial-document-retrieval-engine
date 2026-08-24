from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from typing import TypeVar

Identifier = TypeVar("Identifier")


def recall_at_k(
    ranked_ids: Sequence[Identifier],
    relevant_ids: set[Identifier],
    k: int,
) -> float:
    if not relevant_ids:
        return 0.0
    return len(set(ranked_ids[:k]) & relevant_ids) / len(relevant_ids)


def precision_at_k(
    ranked_ids: Sequence[Identifier],
    relevant_ids: set[Identifier],
    k: int,
) -> float:
    if k <= 0:
        return 0.0
    return len(set(ranked_ids[:k]) & relevant_ids) / k


def issuer_recall_at_k(
    ranked_tickers: Sequence[str],
    relevant_tickers: set[str],
    k: int,
) -> float:
    """Recall over unique issuers rather than retrieved passages."""
    ranked = _unique_normalized_tickers(ranked_tickers)
    relevant = {_normalize_ticker(ticker) for ticker in relevant_tickers}
    return recall_at_k(ranked, relevant, k)


def issuer_precision_at_k(
    ranked_tickers: Sequence[str],
    relevant_tickers: set[str],
    k: int,
) -> float:
    """Precision over unique issuers rather than retrieved passages."""
    ranked = _unique_normalized_tickers(ranked_tickers)
    relevant = {_normalize_ticker(ticker) for ticker in relevant_tickers}
    return precision_at_k(ranked, relevant, k)


def max_issuer_evidence_share(evidence_tickers: Sequence[str]) -> float:
    """Largest issuer share of a returned evidence pool."""
    normalized = [_normalize_ticker(ticker) for ticker in evidence_tickers]
    if not normalized:
        return 0.0
    counts = Counter(normalized)
    return max(counts.values()) / len(normalized)


def reciprocal_rank(
    ranked_ids: Sequence[Identifier],
    relevant_ids: set[Identifier],
) -> float:
    for rank, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    ranked_ids: Sequence[Identifier],
    relevant_ids: set[Identifier],
    k: int,
) -> float:
    gains = [1.0 if chunk_id in relevant_ids else 0.0 for chunk_id in ranked_ids[:k]]
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal_hits = min(len(relevant_ids), k)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / ideal if ideal else 0.0


def binary_precision_recall_f1(
    expected: Sequence[bool],
    predicted: Sequence[bool],
) -> tuple[float, float, float]:
    pairs = list(zip(expected, predicted, strict=True))
    true_positive = sum(wanted and actual for wanted, actual in pairs)
    false_positive = sum(
        not wanted and actual for wanted, actual in pairs
    )
    false_negative = sum(
        wanted and not actual for wanted, actual in pairs
    )
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )
    positive_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    true_negative = sum(not wanted and not actual for wanted, actual in pairs)
    negative_precision = (
        true_negative / (true_negative + false_negative)
        if true_negative + false_negative
        else 0.0
    )
    negative_recall = (
        true_negative / (true_negative + false_positive)
        if true_negative + false_positive
        else 0.0
    )
    negative_f1 = (
        2
        * negative_precision
        * negative_recall
        / (negative_precision + negative_recall)
        if negative_precision + negative_recall
        else 0.0
    )
    return precision, recall, (positive_f1 + negative_f1) / 2


def _unique_normalized_tickers(tickers: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(_normalize_ticker(ticker) for ticker in tickers))


def _normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()
