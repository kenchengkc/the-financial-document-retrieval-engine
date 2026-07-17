from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy.orm import Session

from apps.api.app.config import Settings
from apps.api.app.models import RetrievalResult, RetrievalRun
from fdre.indexing.embeddings import embedding_provider_from_settings
from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.hybrid import HybridRetriever
from fdre.retrieval.preprocess import (
    apply_latest_filing_filter,
    load_company_references,
    preprocess_query,
)
from fdre.retrieval.query import PreprocessedQuery, RetrievalCandidate, SearchFilters
from fdre.retrieval.rerank import reranker_from_settings
from fdre.retrieval.sparse import SparseRetriever

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SearchServiceResult:
    preprocessed: PreprocessedQuery
    candidates: list[RetrievalCandidate]
    latency_ms: int


def search_documents(
    session: Session,
    settings: Settings,
    *,
    query: str,
    filters: SearchFilters,
    top_k: int,
) -> SearchServiceResult:
    started = perf_counter()
    preprocessed = apply_latest_filing_filter(
        session,
        query,
        preprocess_query(
            query,
            companies=load_company_references(session),
            filters=filters,
        ),
    )
    preprocess_done = perf_counter()
    provider = embedding_provider_from_settings(settings)
    retriever = HybridRetriever(DenseRetriever(provider), SparseRetriever())
    candidates = retriever.search(
        session,
        preprocessed.rewritten_queries[0],
        filters=preprocessed.filters,
        limit=max(top_k, settings.rerank_top_n),
    )
    retrieve_done = perf_counter()
    candidates = reranker_from_settings(settings).rerank(
        query,
        candidates,
        top_n=min(top_k, settings.rerank_top_n),
    )
    if settings.min_rerank_score > 0:
        candidates = [
            candidate
            for candidate in candidates
            if (candidate.rerank_score or 0.0) >= settings.min_rerank_score
        ]
    rerank_done = perf_counter()
    latency_ms = round((perf_counter() - started) * 1000)
    logger.info(
        "search stages: preprocess=%dms retrieve=%dms rerank=%dms total=%dms",
        round((preprocess_done - started) * 1000),
        round((retrieve_done - preprocess_done) * 1000),
        round((rerank_done - retrieve_done) * 1000),
        latency_ms,
    )
    retrieval_run = RetrievalRun(
        query=query,
        filters_json=preprocessed.filters.model_dump(mode="json"),
        retriever_variant=f"hybrid+{settings.reranker_provider}",
        latency_ms=latency_ms,
    )
    retrieval_run.results.extend(
        [
            RetrievalResult(
                chunk_id=candidate.chunk_id,
                dense_score=candidate.dense_score,
                sparse_score=candidate.sparse_score,
                hybrid_score=candidate.hybrid_score,
                rerank_score=candidate.rerank_score,
                rank=candidate.rank or rank,
            )
            for rank, candidate in enumerate(candidates, start=1)
        ]
    )
    session.add(retrieval_run)
    session.commit()
    return SearchServiceResult(
        preprocessed=preprocessed,
        candidates=candidates,
        latency_ms=latency_ms,
    )
