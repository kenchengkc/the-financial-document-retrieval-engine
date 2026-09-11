from __future__ import annotations

import argparse
from time import perf_counter

from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import create_db_engine
from fdre.evals.datasets import (
    EvalQuestion,
    compute_dataset_sha256,
    load_jsonl_dataset,
    validate_reviewed_benchmark,
)
from fdre.evals.retrieval_diagnostics import (
    RetrievalDevelopmentDiagnostic,
    build_retrieval_development_diagnostic,
    write_retrieval_development_diagnostics,
)
from fdre.indexing.embeddings import embedding_provider_from_settings
from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.hybrid import HybridRetriever
from fdre.retrieval.preprocess import load_company_references, preprocess_query
from fdre.retrieval.query import SearchFilters
from fdre.retrieval.rerank import reranker_from_settings
from fdre.retrieval.sparse import SparseRetriever
from scripts.benchmarks.eval_guard import require_neon_optin
from scripts.pipelines.retrieval_pipeline import build_benchmark_metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run development-only retrieval stage diagnostics without changing the "
            "published historical benchmark contract"
        )
    )
    parser.add_argument("dataset")
    parser.add_argument("--output-dir", default="data/processed/evals/development-diagnostics")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--require-reviewed",
        action="store_true",
        help="Require the complete reviewed 80/40 benchmark before selecting development cases",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.k <= 0:
        raise ValueError("k must be positive")

    require_neon_optin()
    all_questions = load_jsonl_dataset(args.dataset)
    dataset_sha256 = compute_dataset_sha256(all_questions)
    if args.require_reviewed:
        validate_reviewed_benchmark(all_questions)
    questions = [question for question in all_questions if question.split == "development"]
    if not questions:
        raise ValueError("dataset contains no development questions")

    with Session(create_db_engine()) as session:
        diagnostics = run_development_diagnostics(
            session,
            questions=questions,
            final_k=args.k,
        )
        metadata = build_benchmark_metadata(
            session,
            dataset=args.dataset,
            dataset_sha256=dataset_sha256,
            split="development",
            question_count=len(questions),
            ks=(args.k,),
        )
        json_path, markdown_path = write_retrieval_development_diagnostics(
            args.output_dir,
            diagnostics,
            benchmark_metadata=metadata,
            final_k=args.k,
        )
    print({"json": str(json_path), "markdown": str(markdown_path)})


def run_development_diagnostics(
    session: Session,
    *,
    questions: list[EvalQuestion],
    final_k: int,
) -> list[RetrievalDevelopmentDiagnostic]:
    if final_k <= 0:
        raise ValueError("final_k must be positive")

    settings = get_settings()
    provider = embedding_provider_from_settings(settings)
    hybrid = HybridRetriever(DenseRetriever(provider), SparseRetriever())
    reranker = reranker_from_settings(settings)
    companies = load_company_references(session)
    candidate_limit = max(final_k, settings.rerank_top_n)
    diagnostics: list[RetrievalDevelopmentDiagnostic] = []

    for question in questions:
        scope_started = perf_counter()
        query_scope = preprocess_query(question.question, companies=companies)
        scope_ms = (perf_counter() - scope_started) * 1000

        scoped_started = perf_counter()
        benchmark_scope = preprocess_query(
            question.question,
            companies=companies,
            filters=SearchFilters(
                tickers=question.expected_tickers,
                sections=question.expected_sections,
            ),
        )
        benchmark_scope_ms = (perf_counter() - scoped_started) * 1000

        hybrid_timings: dict[str, int] = {}
        total_started = perf_counter()
        candidate_pool = hybrid.search(
            session,
            question.question,
            filters=benchmark_scope.filters,
            limit=candidate_limit,
            timings_ms=hybrid_timings,
        )
        rerank_started = perf_counter()
        final_candidates = reranker.rerank(
            question.question,
            candidate_pool,
            top_n=final_k,
        )
        rerank_ms = (perf_counter() - rerank_started) * 1000
        total_ms = (perf_counter() - total_started) * 1000
        estimated_tokens = max(1, round(len(question.question.split()) * 1.3))
        stage_timings: dict[str, float] = {
            "query_scope_preprocess": scope_ms,
            "benchmark_scope_preprocess": benchmark_scope_ms,
            **{name: float(value) for name, value in hybrid_timings.items()},
            "rerank": rerank_ms,
            "hybrid_plus_rerank_total": total_ms,
        }
        diagnostics.append(
            build_retrieval_development_diagnostic(
                question,
                inferred_tickers=query_scope.filters.tickers,
                inferred_sections=query_scope.filters.sections,
                candidate_pool=candidate_pool,
                final_candidates=final_candidates,
                final_k=final_k,
                stage_timings_ms=stage_timings,
                estimated_embedding_tokens=estimated_tokens,
                reranker_candidate_count=len(candidate_pool),
            )
        )
    return diagnostics


if __name__ == "__main__":
    main()
