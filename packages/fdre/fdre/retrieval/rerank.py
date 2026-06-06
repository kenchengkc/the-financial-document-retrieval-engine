from __future__ import annotations

import re
from typing import Protocol

from fdre.retrieval.query import RetrievalCandidate

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


class Reranker(Protocol):
    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        *,
        top_n: int,
    ) -> list[RetrievalCandidate]: ...


class NoOpReranker:
    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        *,
        top_n: int,
    ) -> list[RetrievalCandidate]:
        del query
        ranked = [candidate.model_copy(deep=True) for candidate in candidates[:top_n]]
        for rank, candidate in enumerate(ranked, start=1):
            candidate.rerank_score = candidate.hybrid_score
            candidate.rank = rank
        return ranked


class FakeReranker:
    """Deterministic lexical reranker used by tests and local demos."""

    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        *,
        top_n: int,
    ) -> list[RetrievalCandidate]:
        query_tokens = set(TOKEN_PATTERN.findall(query.casefold()))
        reranked = [candidate.model_copy(deep=True) for candidate in candidates[:top_n]]
        for candidate in reranked:
            text_tokens = set(TOKEN_PATTERN.findall(candidate.text.casefold()))
            overlap = len(query_tokens & text_tokens) / max(len(query_tokens), 1)
            candidate.rerank_score = 0.7 * overlap + 0.3 * (
                candidate.hybrid_score or 0.0
            )
        reranked.sort(
            key=lambda candidate: (-(candidate.rerank_score or 0.0), candidate.chunk_id)
        )
        for rank, candidate in enumerate(reranked, start=1):
            candidate.rank = rank
        return reranked


class CrossEncoderReranker:
    def __init__(self, model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model)

    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        *,
        top_n: int,
    ) -> list[RetrievalCandidate]:
        reranked = [candidate.model_copy(deep=True) for candidate in candidates[:top_n]]
        scores = self._model.predict([(query, candidate.text) for candidate in reranked])
        for candidate, score in zip(reranked, scores, strict=True):
            candidate.rerank_score = float(score)
        reranked.sort(
            key=lambda candidate: (-(candidate.rerank_score or 0.0), candidate.chunk_id)
        )
        for rank, candidate in enumerate(reranked, start=1):
            candidate.rank = rank
        return reranked


def reranker_from_name(name: str) -> Reranker:
    if name == "none":
        return NoOpReranker()
    if name == "fake":
        return FakeReranker()
    if name == "cross_encoder":
        return CrossEncoderReranker()
    raise ValueError(f"Unsupported reranker provider: {name}")
