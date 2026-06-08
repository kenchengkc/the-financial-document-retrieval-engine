from __future__ import annotations

import re
from typing import Protocol

from apps.api.app.config import Settings
from fdre.indexing.embeddings import RequestPacer, _post_json_with_retries
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


class VoyageReranker:
    """Rerank candidates with Voyage's hosted cross-encoder (e.g. rerank-2.5)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "rerank-2.5",
        api_url: str = "https://api.voyageai.com/v1/rerank",
        requests_per_minute: int | None = None,
        max_attempts: int = 8,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._api_url = api_url
        self._pacer = (
            RequestPacer(requests_per_minute) if requests_per_minute is not None else None
        )
        self._max_attempts = max_attempts

    def rerank(
        self,
        query: str,
        candidates: list[RetrievalCandidate],
        *,
        top_n: int,
    ) -> list[RetrievalCandidate]:
        if not candidates:
            return []
        subset = [candidate.model_copy(deep=True) for candidate in candidates]
        response = _post_json_with_retries(
            url=self._api_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json_body={
                "query": query,
                "documents": [candidate.text for candidate in subset],
                "model": self.model,
                "top_k": min(top_n, len(subset)),
                "truncation": True,
            },
            timeout=30,
            pacer=self._pacer,
            max_attempts=self._max_attempts,
        )
        reranked: list[RetrievalCandidate] = []
        for item in response.json()["data"]:
            candidate = subset[int(item["index"])]
            candidate.rerank_score = float(item["relevance_score"])
            reranked.append(candidate)
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


def reranker_from_settings(settings: Settings) -> Reranker:
    """Build a reranker from settings, wiring API credentials when needed."""

    if settings.reranker_provider == "voyage":
        if not settings.voyage_api_key:
            raise ValueError("VOYAGE_API_KEY is required for RERANKER_PROVIDER=voyage")
        return VoyageReranker(
            api_key=settings.voyage_api_key,
            model=settings.reranker_model,
        )
    return reranker_from_name(settings.reranker_provider)
