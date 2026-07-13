from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.config import get_settings
from apps.api.app.db import create_db_engine
from apps.api.app.models import Chunk, Company, Document, Embedding, FinancialFact
from apps.api.app.services.operations_service import build_data_quality_report
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
from fdre.research.composite_study import (
    CompositeEvent,
    SignalComponent,
    period_label,
    persist_composite_study,
    run_composite_study,
)
from fdre.research.event_study import (
    EventStudyConfig,
    EventWindow,
    FilingEvent,
    load_filing_events,
    load_market_bars,
    persist_event_study,
    run_event_study,
    write_event_study_report,
)
from fdre.research.market_data import DEFAULT_CACHE_DIR, fetch_market_bars
from fdre.research.panel import (
    PanelFeature,
    ResearchPanelQuery,
    build_research_panel,
    write_research_panel,
)
from fdre.research.signal_study import (
    SignalConstituent,
    SignalStudyReport,
    persist_signal_study,
    run_realized_volatility_signal_study,
    run_signal_study,
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
    signal_parser = subparsers.add_parser(
        "signal-study",
        help="Run a point-in-time filing-feature signal study",
    )
    signal_parser.add_argument("--output", required=True)
    signal_parser.add_argument(
        "--signal",
        choices=(
            "disclosure_similarity",
            "risk_factor_expansion",
            "earnings_quality",
        ),
        default="disclosure_similarity",
    )
    signal_parser.add_argument(
        "--outcome",
        choices=("abnormal_return", "realized_volatility"),
        default="abnormal_return",
    )
    signal_parser.add_argument("--tickers", nargs="+")
    signal_parser.add_argument("--max-tickers", type=int, default=50)
    signal_parser.add_argument("--min-documents", type=int, default=4)
    signal_parser.add_argument("--benchmark", default="SPY")
    signal_parser.add_argument("--n-quantiles", type=int, default=5)
    signal_parser.add_argument("--windows", nargs="+", default=["0:1", "1:21", "1:63"])
    signal_parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    signal_parser.add_argument(
        "--winsorize",
        type=float,
        default=None,
        help="Clip forward returns to the [pct, 1-pct] quantiles per window "
        "(e.g. 0.025) to limit single-name outlier influence in small samples",
    )
    signal_parser.add_argument("--forward-buffer-days", type=int, default=130)
    signal_parser.add_argument(
        "--market-start",
        help="Pin the market-data window start (YYYY-MM-DD) instead of deriving it "
        "from event dates; keeps the cache key stable across universe changes",
    )
    signal_parser.add_argument("--market-end", help="Pin the market-data window end (YYYY-MM-DD)")
    signal_parser.add_argument(
        "--market-cache-dir",
        default=str(DEFAULT_CACHE_DIR),
        help="Local market-data cache directory; use an empty value to disable caching",
    )
    signal_parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Use only cached market data and report uncached symbols as missing",
    )
    signal_parser.add_argument(
        "--fail-on-missing-market-data",
        action="store_true",
        help="Fail instead of publishing when any selected market data is missing",
    )
    signal_parser.add_argument(
        "--max-uncached-market-fetches",
        type=int,
        help="Maximum uncached ticker/benchmark market-data requests for this run",
    )
    signal_parser.add_argument(
        "--market-cache-slice",
        help="Warm only OFFSET:LIMIT selected market tickers, then exit without publishing",
    )
    composite_parser = subparsers.add_parser(
        "composite-study",
        help="Combine several weak filing signals into one cross-sectional composite",
    )
    composite_parser.add_argument("--output", required=True)
    composite_parser.add_argument("--max-tickers", type=int, default=120)
    composite_parser.add_argument("--min-documents", type=int, default=4)
    composite_parser.add_argument("--benchmark", default="SPY")
    composite_parser.add_argument("--n-quantiles", type=int, default=5)
    composite_parser.add_argument("--windows", nargs="+", default=["0:1", "1:21", "1:63"])
    composite_parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    composite_parser.add_argument("--forward-buffer-days", type=int, default=130)
    composite_parser.add_argument(
        "--market-start",
        help="Pin the market-data window start (YYYY-MM-DD) instead of deriving it "
        "from event dates; keeps the cache key stable across universe changes",
    )
    composite_parser.add_argument(
        "--market-end", help="Pin the market-data window end (YYYY-MM-DD)"
    )
    composite_parser.add_argument("--market-cache-dir", default=str(DEFAULT_CACHE_DIR))
    composite_parser.add_argument("--cache-only", action="store_true")
    composite_parser.add_argument("--max-uncached-market-fetches", type=int)
    composite_parser.add_argument(
        "--neutralize",
        choices=("period", "sector"),
        default="period",
        help="period z-scores each signal within its filing quarter; sector adds a"
        " within-(quarter, sector) cross-section where sector breadth allows",
    )
    sectors_parser = subparsers.add_parser(
        "backfill-sectors",
        help="Populate Company.sector/industry from SEC SIC codes",
    )
    sectors_parser.add_argument("--tickers", nargs="+")
    sectors_parser.add_argument("--limit", type=int, default=600)
    sectors_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Refresh companies that already have a sector",
    )
    audit_parser = subparsers.add_parser(
        "audit",
        help="Report corpus freshness, completeness, and indexing integrity",
    )
    audit_parser.add_argument("--stale-after-days", type=int, default=150)
    audit_parser.add_argument("--fail-on-errors", action="store_true")
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
            from scripts.eval_guard import require_neon_optin

            require_neon_optin()
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
        elif args.command == "signal-study":
            print(_run_signal_study(session, args))
        elif args.command == "composite-study":
            print(_run_composite_study(session, args))
        elif args.command == "backfill-sectors":
            print(_run_backfill_sectors(session, args))
        elif args.command == "audit":
            audit_report = build_data_quality_report(
                session,
                stale_after_days=args.stale_after_days,
            )
            print(audit_report.model_dump(mode="json"))
            if args.fail_on_errors and not audit_report.healthy:
                raise SystemExit(1)
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


_ACCRUAL_CONCEPTS = (
    "NetIncomeLoss",
    "NetCashProvidedByUsedInOperatingActivities",
    "Assets",
)


def _earnings_quality_dataset(
    session: Session, tickers: list[str]
) -> tuple[list[FilingEvent], list[SignalConstituent], str]:
    """Build point-in-time earnings-quality (accruals) events from 10-K facts.

    Balance-sheet accruals = (net income - operating cash flow) / total assets.
    Low accruals mean reported earnings are backed by cash, which historically
    predicts stronger forward returns (Sloan 1996), so the study signal is the
    *negated* accrual ratio -- a higher value is higher quality. Constituents are
    the current highest/lowest-quality names by each issuer's most recent 10-K.
    """
    doc_rows = session.execute(
        select(
            Document.id,
            Document.accession_number,
            Document.available_at,
            Document.sha256_hash,
            Company.ticker,
            Company.name,
        )
        .join(Company, Company.id == Document.company_id)
        .where(
            Document.form_type == "10-K",
            Document.available_at.is_not(None),
            Company.ticker.in_(tickers),
        )
        .order_by(Document.available_at, Document.id)
    ).all()
    doc_ids = [row.id for row in doc_rows]
    if not doc_ids:
        return [], [], hashlib.sha256(b"").hexdigest()[:16]
    # Keep the most-recent (period_end) value per (document, concept): the filing's
    # own fiscal year, not prior-year comparatives carried in the same statement.
    best: dict[tuple[int, str], tuple[date, float]] = {}
    for did, concept, value, period_end in session.execute(
        select(
            FinancialFact.document_id,
            FinancialFact.concept,
            FinancialFact.value,
            FinancialFact.period_end,
        ).where(
            FinancialFact.document_id.in_(doc_ids),
            FinancialFact.concept.in_(_ACCRUAL_CONCEPTS),
            FinancialFact.value.is_not(None),
        )
    ).all():
        key = (did, concept)
        stamp = period_end or date.min
        current = best.get(key)
        if current is None or stamp > current[0]:
            best[key] = (stamp, float(value))
    events: list[FilingEvent] = []
    used_docs: list[str] = []
    # ticker -> (available_at, accrual_ratio, name) for the latest filing.
    latest_by_ticker: dict[str, tuple[datetime, float, str]] = {}
    for row in doc_rows:
        ni = best.get((row.id, "NetIncomeLoss"))
        ocf = best.get((row.id, "NetCashProvidedByUsedInOperatingActivities"))
        assets = best.get((row.id, "Assets"))
        if ni is None or ocf is None or assets is None or assets[1] == 0:
            continue
        accruals = (ni[1] - ocf[1]) / assets[1]
        available_at = row.available_at
        events.append(
            FilingEvent(
                ticker=row.ticker,
                accession_number=row.accession_number,
                available_at=available_at,
                max_source_available_at=available_at,
                feature_value=-accruals,
            )
        )
        used_docs.append(f"{row.accession_number}:{row.sha256_hash or ''}")
        prev = latest_by_ticker.get(row.ticker)
        if prev is None or available_at > prev[0]:
            latest_by_ticker[row.ticker] = (available_at, accruals, row.name)
    dataset_version = hashlib.sha256(
        "|".join(used_docs).encode("utf-8")
    ).hexdigest()[:16]
    # Rank current names by accrual ratio: lowest (cash-backed) = long, highest = short.
    ranked = sorted(latest_by_ticker.items(), key=lambda kv: kv[1][1])
    top_n = min(8, len(ranked) // 2)
    constituents: list[SignalConstituent] = []
    for ticker, (_, accruals, name) in ranked[:top_n]:
        constituents.append(
            SignalConstituent(ticker=ticker, name=name, value=accruals, side="long")
        )
    for ticker, (_, accruals, name) in (ranked[-top_n:] if top_n else []):
        constituents.append(
            SignalConstituent(ticker=ticker, name=name, value=accruals, side="short")
        )
    return events, constituents, dataset_version


def _run_signal_study(session: Session, args: argparse.Namespace) -> dict[str, Any]:
    if (
        args.max_uncached_market_fetches is not None
        and args.max_uncached_market_fetches < 0
    ):
        raise SystemExit("--max-uncached-market-fetches must be non-negative.")
    if args.tickers:
        tickers = [ticker.upper() for ticker in args.tickers]
    else:
        rows = session.execute(
            select(Company.ticker, func.count(Document.id))
            .join(Document, Document.company_id == Company.id)
            .group_by(Company.ticker)
            .having(func.count(Document.id) >= args.min_documents)
            .order_by(func.count(Document.id).desc(), Company.ticker)
            .limit(args.max_tickers)
        ).all()
        tickers = [row[0] for row in rows]
    constituents: list[SignalConstituent] = []
    if args.signal == "earnings_quality":
        # Accruals come from structured XBRL facts, not the disclosure panel.
        events, constituents, dataset_version = _earnings_quality_dataset(
            session, tickers
        )
        feature_version = "accruals-v1"
    else:
        panel = build_research_panel(
            session,
            ResearchPanelQuery(
                tickers=tickers,
                features=_signal_panel_features(args.signal),
                limit=10_000,
            ),
        )
        events = [
            FilingEvent(
                ticker=row.ticker,
                accession_number=row.accession_number,
                available_at=row.available_at,
                max_source_available_at=row.max_source_available_at,
                feature_value=_signal_feature_value(row, args.signal),
            )
            for row in panel.rows
        ]
        dataset_version = panel.corpus_snapshot_id
        feature_version = panel.feature_version
    scored = [event for event in events if event.feature_value is not None]
    if len(scored) < args.n_quantiles * 4:
        raise SystemExit(
            f"Only {len(scored)} scored events; ingest more filing history first."
        )
    event_dates = [event.available_at.date() for event in scored]
    start = min(event_dates) - timedelta(days=10)
    end = max(event_dates) + timedelta(days=args.forward_buffer_days)
    if args.market_start:
        start = date.fromisoformat(args.market_start)
    if args.market_end:
        end = date.fromisoformat(args.market_end)
    cache_dir = Path(args.market_cache_dir) if args.market_cache_dir else None
    market_slice = _optional_slice(args.market_cache_slice)
    market_tickers = (
        tickers[market_slice[0] : market_slice[0] + market_slice[1]]
        if market_slice is not None
        else tickers
    )
    bars, missing = fetch_market_bars(
        market_tickers,
        start,
        end,
        benchmark=args.benchmark,
        cache_dir=cache_dir,
        cache_only=args.cache_only,
        max_uncached_fetches=args.max_uncached_market_fetches,
    )
    if market_slice is not None:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": "market_cache_warmed",
            "signal_name": args.signal,
            "outcome_name": args.outcome,
            "tickers": market_tickers,
            "all_selected_tickers": len(tickers),
            "events": len(scored),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "market_bars": len(bars),
            "missing_market_data": missing,
        }
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return {"output": str(output_path), **payload}
    if missing and args.fail_on_missing_market_data:
        raise SystemExit(f"Missing market data for: {', '.join(missing)}")
    config = EventStudyConfig(
        benchmark_ticker=args.benchmark,
        windows=[_event_window(value) for value in args.windows],
        bootstrap_iterations=args.bootstrap_iterations,
    )
    if args.outcome == "realized_volatility":
        report: SignalStudyReport = run_realized_volatility_signal_study(
            scored,
            bars,
            config,
            signal_name=args.signal,
            n_quantiles=args.n_quantiles,
            dataset_version=dataset_version,
            feature_version=feature_version,
            code_sha=_git_sha(),
        )
    else:
        report = run_signal_study(
            scored,
            bars,
            config,
            signal_name=args.signal,
            n_quantiles=args.n_quantiles,
            dataset_version=dataset_version,
            feature_version=feature_version,
            code_sha=_git_sha(),
            outcome_name=args.outcome,
            winsorize_pct=args.winsorize,
        )
    report.constituents = constituents
    if report.event_count == 0:
        raise SystemExit(
            "No filing events had matching market data; refusing to publish an empty study."
        )
    experiment = persist_signal_study(session, report)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return {
        "output": str(output_path),
        "experiment_id": experiment.id,
        "experiment_key": report.experiment_key,
        "signal_name": report.signal_name,
        "outcome_name": report.outcome_name,
        "tickers": len(tickers),
        "events": report.event_count,
        "missing_market_data": missing,
    }


def _run_backfill_sectors(session: Session, args: argparse.Namespace) -> dict[str, Any]:
    from collections import Counter

    from fdre.ingestion.sec_client import SECClient
    from fdre.research.sectors import sic_to_sector

    statement = select(Company).order_by(Company.ticker)
    if args.tickers:
        statement = statement.where(
            Company.ticker.in_([ticker.upper() for ticker in args.tickers])
        )
    elif not args.overwrite:
        statement = statement.where(Company.sector.is_(None))
    companies = list(session.scalars(statement.limit(args.limit)))

    client = SECClient.from_settings()
    counts: Counter[str] = Counter()
    updated = 0
    try:
        for company in companies:
            try:
                submissions = client.get_company_submissions(company.cik)
            except Exception as exc:
                print(f"  skip {company.ticker}: {exc}")
                continue
            sic = submissions.get("sic")
            sector = sic_to_sector(sic)
            company.sector = sector
            description = submissions.get("sicDescription")
            if isinstance(description, str) and description.strip():
                company.industry = description.strip().title()
            counts[sector] += 1
            updated += 1
    finally:
        client.close()
    session.commit()
    return {"companies_updated": updated, "sector_distribution": dict(counts.most_common())}


def _run_composite_study(session: Session, args: argparse.Namespace) -> dict[str, Any]:
    rows = session.execute(
        select(Company.ticker, func.count(Document.id))
        .join(Document, Document.company_id == Company.id)
        .group_by(Company.ticker)
        .having(func.count(Document.id) >= args.min_documents)
        .order_by(func.count(Document.id).desc(), Company.ticker)
        .limit(args.max_tickers)
    ).all()
    tickers = [row[0] for row in rows]
    panel = build_research_panel(
        session,
        ResearchPanelQuery(
            tickers=tickers,
            features=["disclosure_similarity", "risk_changes", "filing_timing"],
            limit=10_000,
        ),
    )
    components = [
        SignalComponent(name="disclosure_similarity", sign=1),
        SignalComponent(name="risk_expansion", sign=-1),
        SignalComponent(name="filing_lateness", sign=-1),
    ]
    events: list[CompositeEvent] = []
    for row in panel.rows:
        # Anchor on a prior comparable filing so every signal is defined and the
        # event universe matches the single-signal studies (and their market cache).
        if row.disclosure_similarity is None:
            continue
        raw: dict[str, float] = {"disclosure_similarity": float(row.disclosure_similarity)}
        if row.risk_added_passages is not None or row.risk_removed_passages is not None:
            raw["risk_expansion"] = float(
                (row.risk_added_passages or 0) - (row.risk_removed_passages or 0)
            )
        if row.filing_delay_days is not None:
            raw["filing_lateness"] = float(row.filing_delay_days)
        if raw:
            events.append(
                CompositeEvent(
                    ticker=row.ticker,
                    accession_number=row.accession_number,
                    available_at_period=period_label(row.available_at.date()),
                    available_at=row.available_at,
                    max_source_available_at=row.max_source_available_at,
                    raw=raw,
                )
            )
    if len(events) < args.n_quantiles * 4:
        raise SystemExit(f"Only {len(events)} composite events; ingest more history.")
    event_dates = [event.available_at.date() for event in events]
    start = min(event_dates) - timedelta(days=10)
    end = max(event_dates) + timedelta(days=args.forward_buffer_days)
    if args.market_start:
        start = date.fromisoformat(args.market_start)
    if args.market_end:
        end = date.fromisoformat(args.market_end)
    bars, missing = fetch_market_bars(
        tickers,
        start,
        end,
        benchmark=args.benchmark,
        cache_dir=Path(args.market_cache_dir) if args.market_cache_dir else None,
        cache_only=args.cache_only,
        max_uncached_fetches=args.max_uncached_market_fetches,
    )
    config = EventStudyConfig(
        benchmark_ticker=args.benchmark,
        windows=[_event_window(value) for value in args.windows],
        bootstrap_iterations=args.bootstrap_iterations,
    )
    sector_by_accession: dict[str, str] | None = None
    if args.neutralize == "sector":
        ticker_sector: dict[str, str | None] = {
            row.ticker: row.sector
            for row in session.execute(
                select(Company.ticker, Company.sector).where(Company.ticker.in_(tickers))
            )
        }
        sector_by_accession = {
            event.accession_number: (ticker_sector.get(event.ticker) or "Unknown")
            for event in events
        }
    report = run_composite_study(
        events,
        components,
        bars,
        config,
        n_quantiles=args.n_quantiles,
        dataset_version=panel.corpus_snapshot_id,
        feature_version=panel.feature_version,
        code_sha=_git_sha(),
        sector_by_accession=sector_by_accession,
    )
    if report.event_count == 0:
        raise SystemExit("No composite events had matching market data; refusing to publish.")
    experiment = persist_composite_study(session, report)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    return {
        "output": str(output_path),
        "experiment_id": experiment.id,
        "events": report.event_count,
        "components": report.component_signals,
        "neutralization": report.neutralization,
        "missing_market_data": missing,
    }


def _signal_panel_features(signal_name: str) -> list[PanelFeature]:
    if signal_name == "risk_factor_expansion":
        return ["risk_changes"]
    return ["disclosure_similarity"]


def _signal_feature_value(row: Any, signal_name: str) -> float | None:
    if signal_name == "risk_factor_expansion":
        if row.risk_added_passages is None and row.risk_removed_passages is None:
            return None
        return float((row.risk_added_passages or 0) - (row.risk_removed_passages or 0))
    return cast(float | None, row.disclosure_similarity)


def _optional_slice(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    offset_text, separator, limit_text = value.partition(":")
    if not separator:
        raise SystemExit("--market-cache-slice must use OFFSET:LIMIT.")
    offset = int(offset_text)
    limit = int(limit_text)
    if offset < 0 or limit < 1:
        raise SystemExit("--market-cache-slice requires offset >= 0 and limit >= 1.")
    return offset, limit


if __name__ == "__main__":
    main()
