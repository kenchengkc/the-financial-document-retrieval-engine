from __future__ import annotations

import argparse
import hashlib
import subprocess
from datetime import UTC, date, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import create_db_engine
from apps.api.app.models import Chunk, Company, Document, Embedding
from fdre.chunking import rebuild_document_chunks
from fdre.demo import seed_demo_document
from fdre.evals.datasets import (
    EvalQuestion,
    load_jsonl_dataset,
    validate_reviewed_benchmark,
)
from fdre.evals.runner import (
    EvaluationOutcome,
    VariantMetrics,
    evaluate_variants,
    write_eval_report,
)
from fdre.indexing.embeddings import embedding_provider_from_settings, rebuild_embeddings
from fdre.ingestion.sec_client import SECClient
from fdre.ingestion.xbrl import ingest_company_facts
from fdre.research.event_study import (
    EventStudyConfig,
    EventWindow,
    load_filing_events,
    load_market_bars,
    persist_event_study,
    run_event_study,
    write_event_study_report,
)
from fdre.research.panel import (
    ResearchPanelQuery,
    build_research_panel,
    write_research_panel,
)
from fdre.retrieval.dense import DenseRetriever
from fdre.retrieval.hybrid import HybridRetriever
from fdre.retrieval.preprocess import load_company_references, preprocess_query
from fdre.retrieval.query import SearchFilters
from fdre.retrieval.rerank import reranker_from_name
from fdre.retrieval.sparse import SparseRetriever


def chunk_selected_documents(
    session: Session,
    *,
    tickers: list[str] | None,
    max_tokens: int,
    force_rechunk: bool = False,
) -> tuple[int, int]:
    statement = select(Document).join(Document.company).order_by(Document.id)
    if tickers:
        statement = statement.where(Company.ticker.in_([ticker.upper() for ticker in tickers]))
    documents = list(session.scalars(statement))

    chunk_count = 0
    for document in documents:
        if document.chunks and not force_rechunk:
            continue
        chunk_count += len(
            rebuild_document_chunks(session, document.id, max_tokens=max_tokens)
        )
    return len(documents), chunk_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build FDRE retrieval artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    chunk_parser = subparsers.add_parser("chunk", help="Build document chunks")
    chunk_parser.add_argument("--tickers", nargs="+")
    chunk_parser.add_argument("--max-tokens", type=int, default=220)
    chunk_parser.add_argument(
        "--force-rechunk",
        action="store_true",
        help="Rebuild chunks even when a document already has stored chunks",
    )
    index_parser = subparsers.add_parser("index", help="Build missing stored chunk embeddings")
    index_parser.add_argument("--tickers", nargs="+", help="Limit indexing to these tickers")
    index_parser.add_argument(
        "--document-ids",
        nargs="+",
        type=int,
        help="Limit indexing to these document IDs",
    )
    eval_parser = subparsers.add_parser("eval", help="Run retrieval evaluation")
    eval_parser.add_argument("dataset")
    eval_parser.add_argument("--output-dir", default="data/processed/evals")
    eval_parser.add_argument("--k", type=int, default=10)
    eval_parser.add_argument(
        "--split",
        choices=("development", "holdout", "all"),
        default="development",
    )
    xbrl_parser = subparsers.add_parser(
        "xbrl",
        help="Ingest SEC Company Facts for indexed filing accessions",
    )
    xbrl_parser.add_argument("--tickers", nargs="+")
    panel_parser = subparsers.add_parser(
        "panel",
        help="Export the point-in-time issuer-period research panel",
    )
    panel_parser.add_argument("--output", required=True)
    panel_parser.add_argument(
        "--format",
        choices=("json", "csv", "parquet"),
        default="parquet",
    )
    panel_parser.add_argument("--tickers", nargs="+")
    panel_parser.add_argument("--forms", nargs="+", default=["10-K", "10-Q"])
    panel_parser.add_argument("--period-end-from")
    panel_parser.add_argument("--period-end-to")
    panel_parser.add_argument("--as-of")
    panel_parser.add_argument("--sections", nargs="+")
    panel_parser.add_argument("--features", nargs="+")
    panel_parser.add_argument("--include-amendments", action="store_true")
    panel_parser.add_argument("--limit", type=int, default=1000)
    event_parser = subparsers.add_parser(
        "event-study",
        help="Run a benchmark-adjusted filing event study",
    )
    event_parser.add_argument("--panel", required=True)
    event_parser.add_argument("--market-bars", required=True)
    event_parser.add_argument("--output", required=True)
    event_parser.add_argument("--feature")
    event_parser.add_argument("--benchmark", default="SPY")
    event_parser.add_argument(
        "--windows",
        nargs="+",
        default=["0:1", "-1:1", "0:5"],
    )
    event_parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    event_parser.add_argument("--confidence-level", type=float, default=0.95)
    event_parser.add_argument("--random-seed", type=int, default=17)
    event_parser.add_argument("--walk-forward-splits", nargs="+")
    eval_parser.add_argument(
        "--require-reviewed",
        action="store_true",
        help="Require the complete reviewed 80/40 benchmark contract",
    )
    subparsers.add_parser(
        "seed-demo",
        help="Load the checked-in sample filing and build its retrieval artifacts",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with Session(create_db_engine()) as session:
        if args.command == "chunk":
            documents, chunks = chunk_selected_documents(
                session,
                tickers=args.tickers,
                max_tokens=args.max_tokens,
                force_rechunk=args.force_rechunk,
            )
            print({"documents": documents, "chunks": chunks})
        elif args.command == "index":
            settings = get_settings()
            provider = embedding_provider_from_settings(settings)
            print(
                {
                    "embeddings": rebuild_embeddings(
                        session,
                        provider,
                        tickers=args.tickers,
                        document_ids=args.document_ids,
                        missing_only=True,
                        batch_size=settings.embedding_batch_size,
                        concurrency=settings.embedding_concurrency,
                    )
                }
            )
        elif args.command == "eval":
            questions = load_jsonl_dataset(args.dataset)
            if args.require_reviewed:
                validate_reviewed_benchmark(questions)
            if args.split != "all":
                questions = [
                    question for question in questions if question.split == args.split
                ]
            metrics = run_retrieval_eval(
                session,
                questions=questions,
                k=args.k,
            )
            paths = write_eval_report(
                args.output_dir,
                metrics,
                k=args.k,
                benchmark_metadata=build_benchmark_metadata(
                    session,
                    dataset=args.dataset,
                    split=args.split,
                    question_count=len(questions),
                    k=args.k,
                ),
            )
            print({"json": str(paths[0]), "markdown": str(paths[1])})
        elif args.command == "xbrl":
            with SECClient.from_settings() as client:
                print(
                    ingest_company_facts(
                        session,
                        client,
                        tickers=args.tickers,
                    )
                )
        elif args.command == "panel":
            panel = build_research_panel(
                session,
                ResearchPanelQuery(
                    tickers=args.tickers or [],
                    period_end_from=_optional_date(args.period_end_from),
                    period_end_to=_optional_date(args.period_end_to),
                    as_of=_optional_datetime(args.as_of),
                    form_types=args.forms,
                    sections=args.sections or [],
                    features=args.features or [],
                    include_amendments=args.include_amendments,
                    limit=args.limit,
                ),
            )
            output = write_research_panel(
                args.output,
                panel,
                output_format=args.format,
            )
            print(
                {
                    "output": str(output),
                    "rows": len(panel.rows),
                    "corpus_snapshot_id": panel.corpus_snapshot_id,
                    "feature_version": panel.feature_version,
                }
            )
        elif args.command == "event-study":
            events, dataset_version, feature_version = load_filing_events(
                args.panel,
                feature=args.feature,
            )
            report = run_event_study(
                events,
                load_market_bars(args.market_bars),
                EventStudyConfig(
                    benchmark_ticker=args.benchmark,
                    windows=[_event_window(value) for value in args.windows],
                    bootstrap_iterations=args.bootstrap_iterations,
                    confidence_level=args.confidence_level,
                    random_seed=args.random_seed,
                    walk_forward_splits=[
                        date.fromisoformat(value)
                        for value in args.walk_forward_splits or []
                    ],
                ),
                dataset_version=dataset_version,
                feature_version=feature_version,
                code_sha=_git_sha(),
            )
            experiment = persist_event_study(session, report)
            output = write_event_study_report(args.output, report)
            print(
                {
                    "output": str(output),
                    "experiment_id": experiment.id,
                    "experiment_key": report.experiment_key,
                    "events": report.event_count,
                }
            )
        elif args.command == "seed-demo":
            print(seed_demo_document(session))


def run_retrieval_eval(
    session: Session,
    *,
    questions: list[EvalQuestion],
    k: int,
) -> list[VariantMetrics]:
    settings = get_settings()
    provider = embedding_provider_from_settings(settings)
    dense = DenseRetriever(provider)
    sparse = SparseRetriever()
    hybrid = HybridRetriever(dense, sparse)
    companies = load_company_references(session)

    def retrieve(question: EvalQuestion, variant: str) -> EvaluationOutcome:
        started = perf_counter()
        preprocessed = preprocess_query(
            question.question,
            companies=companies,
            filters=SearchFilters(
                tickers=question.expected_tickers,
                sections=question.expected_sections,
            ),
        )
        if variant == "dense":
            candidates = dense.search(
                session,
                question.question,
                filters=preprocessed.filters,
                limit=k,
            )
        elif variant == "sparse":
            candidates = sparse.search(
                session,
                question.question,
                filters=preprocessed.filters,
                limit=k,
            )
        else:
            candidates = hybrid.search(
                session,
                question.question,
                filters=preprocessed.filters,
                limit=max(k, settings.rerank_top_n),
            )
            candidates = (
                candidates[:k]
                if variant == "hybrid"
                else reranker_from_name(settings.reranker_provider).rerank(
                    question.question,
                    candidates,
                    top_n=k,
                )
            )
        estimated_tokens = max(1, round(len(question.question.split()) * 1.3))
        return EvaluationOutcome(
            candidates=candidates,
            latency_ms=(perf_counter() - started) * 1000,
            provider_cost_usd=(
                estimated_tokens
                * settings.embedding_cost_per_million_tokens
                / 1_000_000
                if variant != "sparse"
                else 0.0
            ),
            abstained=not candidates,
            inferred_tickers=tuple(preprocessed.filters.tickers),
        )

    return evaluate_variants(
        questions,
        {
            "Dense only": lambda question: retrieve(question, "dense"),
            "Sparse only": lambda question: retrieve(question, "sparse"),
            "Hybrid": lambda question: retrieve(question, "hybrid"),
            "Hybrid + reranker": lambda question: retrieve(question, "rerank"),
        },
        k=k,
    )


def build_benchmark_metadata(
    session: Session,
    *,
    dataset: str,
    split: str,
    question_count: int,
    k: int,
) -> dict[str, Any]:
    settings = get_settings()
    document_count = session.scalar(select(func.count()).select_from(Document)) or 0
    chunk_count = session.scalar(select(func.count()).select_from(Chunk)) or 0
    embedding_count = session.scalar(select(func.count()).select_from(Embedding)) or 0
    snapshot_source = (
        f"{document_count}:{chunk_count}:{embedding_count}:"
        f"{settings.embedding_provider}:{settings.embedding_model}:"
        f"{settings.embedding_dimensions}"
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(dataset),
        "split": split,
        "question_count": question_count,
        "corpus_snapshot_id": hashlib.sha256(snapshot_source.encode()).hexdigest()[:16],
        "document_count": document_count,
        "chunk_count": chunk_count,
        "embedding_count": embedding_count,
        "git_sha": _git_sha(),
        "parser_version": "html-filing-parser-v1",
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "reranker_provider": settings.reranker_provider,
        "reranker_model": settings.reranker_model,
        "retrieval_k": k,
        "embedding_cost_per_million_tokens": (
            settings.embedding_cost_per_million_tokens
        ),
    }


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _event_window(value: str) -> EventWindow:
    start, separator, end = value.partition(":")
    if not separator:
        raise ValueError(f"Invalid event window {value!r}; expected START:END")
    return EventWindow(start=int(start), end=int(end))


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


if __name__ == "__main__":
    main()
