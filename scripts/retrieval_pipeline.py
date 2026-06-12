from __future__ import annotations

import argparse
import hashlib
import subprocess
from datetime import UTC, datetime
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
    try:
        git_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        git_sha = "unknown"
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(dataset),
        "split": split,
        "question_count": question_count,
        "corpus_snapshot_id": hashlib.sha256(snapshot_source.encode()).hexdigest()[:16],
        "document_count": document_count,
        "chunk_count": chunk_count,
        "embedding_count": embedding_count,
        "git_sha": git_sha,
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


if __name__ == "__main__":
    main()
