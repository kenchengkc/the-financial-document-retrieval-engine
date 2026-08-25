from __future__ import annotations

import argparse
import hashlib
import subprocess
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import create_db_engine
from apps.api.app.models import Chunk, Document, Embedding
from apps.api.app.services.retrieval_service import search_documents
from fdre.evals import (
    build_cross_sectional_screen_plan,
    compute_dataset_sha256,
    load_cross_sectional_benchmark,
    load_jsonl_dataset,
    run_cross_sectional_benchmark,
    validate_benchmark,
    validate_reviewed_benchmark,
    write_cross_sectional_eval_report,
)
from fdre.evals.datasets import EvalQuestion
from fdre.research.panel import FEATURE_VERSION
from fdre.research.screen import (
    ResearchScreenPlan,
    ResearchScreenResponse,
    execute_research_screen,
)
from fdre.retrieval.query import RetrievalCandidate, SearchFilters
from scripts.eval_guard import require_neon_optin

DEFAULT_DATASET = "data/evals/cross_sectional_benchmark.v1.jsonl"
DEFAULT_SOURCE_DATASET = "data/evals/retrieval_benchmark.jsonl"
DEFAULT_OUTPUT_DIR = "data/processed/evals/cross-sectional-v1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen FDRE cross-sectional benchmark"
    )
    parser.add_argument("dataset", nargs="?", default=DEFAULT_DATASET)
    parser.add_argument("--source-dataset", default=DEFAULT_SOURCE_DATASET)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--split",
        choices=("development", "holdout", "all"),
        default="development",
    )
    parser.add_argument(
        "--ks",
        nargs="+",
        type=int,
        default=[1, 3, 5],
        help="Issuer-ranking cutoffs; defaults to 1 3 5 for the five-issuer v1 cases",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    require_neon_optin()

    raw_questions = load_jsonl_dataset(args.dataset)
    source_questions = load_jsonl_dataset(args.source_dataset)
    validate_reviewed_benchmark(source_questions)
    hydrated_questions = load_cross_sectional_benchmark(
        args.dataset,
        source_dataset_path=args.source_dataset,
    )
    validate_benchmark(
        hydrated_questions,
        expected_count=30,
        expected_splits={"development": 24, "holdout": 6},
        required_categories={"cross_sectional"},
    )

    questions = hydrated_questions
    if args.split != "all":
        questions = [question for question in questions if question.split == args.split]
    if not questions:
        raise ValueError(f"No benchmark questions selected for split {args.split!r}")

    requested_ks = tuple(args.ks)
    settings = get_settings()
    with Session(create_db_engine()) as session:
        metrics = run_cross_sectional_benchmark(
            questions,
            execute_screen=_production_screen_executor(session, settings),
            ks=requested_ks,
        )
        metadata = build_cross_sectional_benchmark_metadata(
            session,
            settings=settings,
            dataset=args.dataset,
            dataset_sha256=compute_dataset_sha256(raw_questions),
            hydrated_dataset_sha256=compute_dataset_sha256(hydrated_questions),
            source_dataset=args.source_dataset,
            source_dataset_sha256=compute_dataset_sha256(source_questions),
            evaluated_subset_sha256=compute_dataset_sha256(questions),
            split=args.split,
            questions=questions,
            ks=metrics.ks,
        )
        paths = write_cross_sectional_eval_report(
            args.output_dir,
            metrics,
            benchmark_metadata=metadata,
        )

    print(
        {
            "json": str(paths[0]),
            "markdown": str(paths[1]),
            "per_query": str(paths[2]),
            "questions": metrics.question_count,
            "issuer_recall_at_k": metrics.issuer_recall_at_k,
            "evidence_recall_at_k": metrics.evidence_recall_at_k,
            "pit_leakage_rate": metrics.pit_leakage_rate,
            "latency_p95_ms": metrics.latency_p95_ms,
        }
    )


def _production_screen_executor(
    session: Session,
    settings: Settings,
) -> Callable[[ResearchScreenPlan], ResearchScreenResponse]:
    def semantic_search(
        query: str,
        filters: SearchFilters,
        top_k: int,
    ) -> list[RetrievalCandidate]:
        return search_documents(
            session,
            settings,
            query=query,
            filters=filters,
            top_k=top_k,
        ).candidates

    def execute(plan: ResearchScreenPlan) -> ResearchScreenResponse:
        return execute_research_screen(
            session,
            plan,
            semantic_search=semantic_search,
        )

    return execute


def build_cross_sectional_benchmark_metadata(
    session: Session,
    *,
    settings: Settings,
    dataset: str,
    dataset_sha256: str,
    hydrated_dataset_sha256: str,
    source_dataset: str,
    source_dataset_sha256: str,
    evaluated_subset_sha256: str,
    split: str,
    questions: list[EvalQuestion],
    ks: tuple[int, ...],
) -> dict[str, Any]:
    document_count = session.scalar(select(func.count()).select_from(Document)) or 0
    chunk_count = session.scalar(select(func.count()).select_from(Chunk)) or 0
    embedding_count = session.scalar(select(func.count()).select_from(Embedding)) or 0
    snapshot_source = (
        f"{document_count}:{chunk_count}:{embedding_count}:"
        f"{settings.embedding_provider}:{settings.embedding_model}:"
        f"{settings.embedding_dimensions}"
    )
    plans = [build_cross_sectional_screen_plan(question) for question in questions]
    task_counts = Counter(question.resolved_task_type for question in questions)
    return {
        "benchmark_name": "FDRE Cross-Sectional v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(Path(dataset)),
        "dataset_sha256": dataset_sha256,
        "hydrated_dataset_sha256": hydrated_dataset_sha256,
        "source_dataset": str(Path(source_dataset)),
        "source_dataset_sha256": source_dataset_sha256,
        "evaluated_subset_sha256": evaluated_subset_sha256,
        "split": split,
        "question_count": len(questions),
        "task_type_counts": dict(sorted(task_counts.items())),
        "issuer_ks": list(ks),
        "corpus_snapshot_id": hashlib.sha256(snapshot_source.encode()).hexdigest()[:16],
        "document_count": document_count,
        "chunk_count": chunk_count,
        "embedding_count": embedding_count,
        "feature_version": FEATURE_VERSION,
        "git_sha": _git_sha(),
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "reranker_provider": settings.reranker_provider,
        "reranker_model": settings.reranker_model,
        "rerank_top_n": settings.rerank_top_n,
        "min_rerank_score": settings.min_rerank_score,
        "semantic_candidate_limits": sorted(
            {plan.semantic_candidate_limit for plan in plans}
        ),
        "result_limits": sorted({plan.limit for plan in plans}),
        "screen_retrieval_path": f"hybrid+{settings.reranker_provider}",
    }


def _git_sha() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return f"{sha}-dirty" if dirty else sha
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


if __name__ == "__main__":
    main()
