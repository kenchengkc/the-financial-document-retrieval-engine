from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from apps.api.app.config import Settings, get_settings
from apps.api.app.db import create_db_engine
from apps.api.app.models import Chunk, Company, Document, Embedding
from apps.api.app.services.operations_service import (
    finish_ingestion_run,
    start_ingestion_run,
)
from fdre.ingestion.ticker_map import (
    DEFAULT_SAMPLE_TICKERS,
    RESEARCH_UNIVERSE_TICKERS,
    sp500_batch_tickers,
)

try:
    from scripts.ingestion_lock import serialized_ingestion
except ModuleNotFoundError:  # pragma: no cover - supports direct script execution
    from ingestion_lock import serialized_ingestion


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run SEC ingest pipeline for a ticker batch (metadata → parse → chunk → index)"
    )
    parser.add_argument(
        "--universe",
        choices=["megacap", "sp500", "research50"],
        default="megacap",
        help="Ticker universe to ingest",
    )
    parser.add_argument("--tickers", nargs="+", help="Explicit tickers (overrides universe)")
    parser.add_argument("--offset", type=int, default=0, help="Batch offset for sp500 universe")
    parser.add_argument("--limit", type=int, default=10, help="Batch size")
    parser.add_argument("--forms", nargs="+", default=["10-K", "10-Q"])
    parser.add_argument("--filing-limit", type=int, default=1, help="Latest N filings per form")
    parser.add_argument("--annual-limit", type=int)
    parser.add_argument("--quarterly-limit", type=int)
    parser.add_argument("--force-parse", action="store_true")
    parser.add_argument("--force-rechunk", action="store_true")
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Skip metadata/download/chunk; only build missing embeddings for tickers",
    )
    parser.add_argument(
        "--skip-if-locked",
        action="store_true",
        help="Exit successfully when another Postgres ingestion already holds the lock",
    )
    return parser.parse_args()


def _selected_tickers(args: argparse.Namespace) -> list[str]:
    if args.tickers:
        return [ticker.upper() for ticker in args.tickers]
    if args.universe == "sp500":
        return sp500_batch_tickers(offset=args.offset, limit=args.limit)
    if args.universe == "research50":
        return list(RESEARCH_UNIVERSE_TICKERS[args.offset : args.offset + args.limit])
    return list(DEFAULT_SAMPLE_TICKERS)


def _run(command: list[str]) -> int:
    print({"run": " ".join(command)}, flush=True)
    started = perf_counter()
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return round((perf_counter() - started) * 1000)


def main() -> None:
    args = parse_args()
    tickers = _selected_tickers(args)
    if not tickers:
        print({"status": "empty_batch", "offset": args.offset, "limit": args.limit})
        return

    settings = get_settings()
    engine = create_db_engine()
    with serialized_ingestion(engine, skip_if_locked=args.skip_if_locked) as acquired:
        if not acquired:
            return
        _run_ingestion(args, tickers, settings, engine)


def _run_ingestion(
    args: argparse.Namespace,
    tickers: list[str],
    settings: Settings,
    engine: Engine,
) -> None:
    ticker_args = ["--tickers", *tickers]
    form_args = ["--forms", *args.forms]
    run_key = uuid4().hex
    run_started = datetime.now(UTC)
    with Session(engine) as session:
        start_ingestion_run(
            session,
            run_key=run_key,
            pipeline="ticker_batch",
            config={
                "universe": args.universe,
                "tickers": tickers,
                "forms": args.forms,
                "filing_limit": args.filing_limit,
                "annual_limit": args.annual_limit,
                "quarterly_limit": args.quarterly_limit,
                "force_parse": args.force_parse,
                "force_rechunk": args.force_rechunk,
                "index_only": args.index_only,
                "embedding_provider": settings.embedding_provider,
                "embedding_model": settings.embedding_model,
            },
        )
        before = _snapshot(session, tickers, started_at=run_started)

    stage_counts: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    pipeline_started = perf_counter()
    status = "completed"
    try:
        if not args.index_only:
            history_args = ["--limit", str(args.filing_limit)]
            if args.annual_limit is not None:
                history_args.extend(["--annual-limit", str(args.annual_limit)])
            if args.quarterly_limit is not None:
                history_args.extend(["--quarterly-limit", str(args.quarterly_limit)])
            stage_counts["metadata"] = {
                "latency_ms": _run(
                    [
                        sys.executable,
                        "scripts/ingest_sec_sample.py",
                        *ticker_args,
                        *form_args,
                        *history_args,
                    ]
                ),
                "status": "completed",
            }

            download_cmd = [
                sys.executable,
                "-m",
                "scripts.download_filings",
                *ticker_args,
                *form_args,
                "--limit",
                str(args.filing_limit),
                "--download",
                "--parse",
            ]
            if args.annual_limit is not None:
                download_cmd.extend(["--annual-limit", str(args.annual_limit)])
            if args.quarterly_limit is not None:
                download_cmd.extend(["--quarterly-limit", str(args.quarterly_limit)])
            if args.force_parse:
                download_cmd.append("--force-parse")
            stage_counts["download_parse"] = {
                "latency_ms": _run(download_cmd),
                "status": "completed",
            }

            chunk_cmd = [
                sys.executable,
                "-m",
                "scripts.retrieval_pipeline",
                "chunk",
                *ticker_args,
            ]
            if args.force_rechunk:
                chunk_cmd.append("--force-rechunk")
            stage_counts["chunk"] = {
                "latency_ms": _run(chunk_cmd),
                "status": "completed",
            }

        stage_counts["index"] = {
            "latency_ms": _run(
                [
                    sys.executable,
                    "-m",
                    "scripts.retrieval_pipeline",
                    "index",
                    *ticker_args,
                ]
            ),
            "status": "completed",
        }
    except subprocess.CalledProcessError as error:
        status = "failed"
        failed_command = (
            [str(part) for part in error.cmd]
            if isinstance(error.cmd, list)
            else [str(error.cmd)]
        )
        failures.append(
            {
                "command": " ".join(failed_command),
                "return_code": error.returncode,
                "stdout": (error.stdout or "")[-4000:],
                "stderr": (error.stderr or "")[-4000:],
            }
        )
        raise
    finally:
        with Session(engine) as session:
            after = _snapshot(session, tickers, started_at=run_started)
            deltas = {
                key: after[key] - before[key]
                for key in ("documents", "chunks", "embeddings", "embedding_tokens")
            }
            stage_counts["totals"] = {
                **after,
                **{f"new_{key}": value for key, value in deltas.items()},
            }
            estimated_cost = Decimal(
                str(
                    max(deltas["embedding_tokens"], 0)
                    * settings.embedding_cost_per_million_tokens
                    / 1_000_000
                )
            )
            finish_ingestion_run(
                session,
                run_key=run_key,
                status=status,
                stage_counts=stage_counts,
                failures=failures,
                retry_count=0,
                latency_ms=round((perf_counter() - pipeline_started) * 1000),
                provider_usage={
                    "provider": settings.embedding_provider,
                    "model": settings.embedding_model,
                    "new_embeddings": max(deltas["embeddings"], 0),
                    "estimated_tokens": max(deltas["embedding_tokens"], 0),
                },
                estimated_cost_usd=estimated_cost,
            )

    print(
        {
            "status": "completed",
            "universe": args.universe,
            "tickers": tickers,
            "offset": args.offset,
            "limit": args.limit,
            "run_key": run_key,
        }
    )


def _snapshot(
    session: Session,
    tickers: list[str],
    *,
    started_at: datetime,
) -> dict[str, int]:
    ticker_filter = Company.ticker.in_(tickers)
    documents = session.scalar(
        select(func.count())
        .select_from(Document)
        .join(Company, Company.id == Document.company_id)
        .where(ticker_filter)
    ) or 0
    chunks = session.scalar(
        select(func.count())
        .select_from(Chunk)
        .join(Document, Document.id == Chunk.document_id)
        .join(Company, Company.id == Document.company_id)
        .where(ticker_filter)
    ) or 0
    embeddings = session.scalar(
        select(func.count())
        .select_from(Embedding)
        .join(Chunk, Chunk.id == Embedding.chunk_id)
        .join(Document, Document.id == Chunk.document_id)
        .join(Company, Company.id == Document.company_id)
        .where(ticker_filter)
    ) or 0
    embedding_tokens = session.scalar(
        select(func.coalesce(func.sum(Chunk.token_count), 0))
        .select_from(Embedding)
        .join(Chunk, Chunk.id == Embedding.chunk_id)
        .join(Document, Document.id == Chunk.document_id)
        .join(Company, Company.id == Document.company_id)
        .where(
            ticker_filter,
            Embedding.created_at >= started_at,
        )
    ) or 0
    return {
        "documents": int(documents),
        "chunks": int(chunks),
        "embeddings": int(embeddings),
        "embedding_tokens": int(embedding_tokens),
    }


if __name__ == "__main__":
    main()
