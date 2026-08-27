from __future__ import annotations

import logging
from dataclasses import dataclass, field
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
    stage_timings_ms: dict[str, int] = field(default_factory=dict)


def search_documents(
    session: Session,
    settings: Settings,
    *,
    query: str,
    filters: SearchFilters,
    top_k: int,
) -> SearchServiceResult:
    started = perf_counter()

    preprocess_started = perf_counter()
    preprocessed = apply_latest_filing_filter(
        session,
        query,
        preprocess_query(
            query,
            companies=load_company_references(session),
            filters=filters,
        ),
    )
    preprocess_ms = round((perf_counter() - preprocess_started) * 1000)

    provider_started = perf_counter()
    provider = embedding_provider_from_settings(settings)
    retriever = HybridRetriever(DenseRetriever(provider), SparseRetriever())
    provider_init_ms = round((perf_counter() - provider_started) * 1000)

    hybrid_timings: dict[str, int] = {}
    retrieve_started = perf_counter()
    candidates = retriever.search(
        session,
        preprocessed.rewritten_queries[0],
        filters=preprocessed.filters,
        limit=max(top_k, settings.rerank_top_n),
        timings_ms=hybrid_timings,
    )
    retrieve_ms = round((perf_counter() - retrieve_started) * 1000)

    rerank_started = perf_counter()
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
    rerank_ms = round((perf_counter() - rerank_started) * 1000)

    # Preserve the historical retrieval latency definition: query processing through
    # ranking, excluding the audit-row commit below. The full service wall time is
    # reported separately in stage_timings_ms for production profiling.
    latency_ms = round((perf_counter() - started) * 1000)

    persist_started = perf_counter()
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
    audit_persist_ms = round((perf_counter() - persist_started) * 1000)
    service_total_ms = round((perf_counter() - started) * 1000)

    stage_timings_ms = {
        "preprocess": preprocess_ms,
        "provider_init": provider_init_ms,
        "embedding": hybrid_timings.get("embedding", 0),
        "dense": hybrid_timings.get("dense", 0),
        "sparse": hybrid_timings.get("sparse", 0),
        "fusion": hybrid_timings.get("fusion", 0),
        "retrieve_total": retrieve_ms,
        "rerank": rerank_ms,
        "audit_persist": audit_persist_ms,
        "service_total": service_total_ms,
    }
    logger.info(
        "search stages: preprocess=%dms provider_init=%dms embedding=%dms "
        "dense=%dms sparse=%dms fusion=%dms rerank=%dms audit_persist=%dms total=%dms",
        preprocess_ms,
        provider_init_ms,
        stage_timings_ms["embedding"],
        stage_timings_ms["dense"],
        stage_timings_ms["sparse"],
        stage_timings_ms["fusion"],
        rerank_ms,
        audit_persist_ms,
        service_total_ms,
    )
    return SearchServiceResult(
        preprocessed=preprocessed,
        candidates=candidates,
        latency_ms=latency_ms,
        stage_timings_ms=stage_timings_ms,
    )
