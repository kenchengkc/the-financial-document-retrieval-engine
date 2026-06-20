from __future__ import annotations

import argparse
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company, FinancialFact
from apps.api.app.services.operations_service import (
    finish_ingestion_run,
    start_ingestion_run,
)
from fdre.ingestion.sec_client import SECClient
from fdre.ingestion.ticker_map import (
    DEFAULT_SAMPLE_TICKERS,
    RESEARCH_UNIVERSE_TICKERS,
    sp500_batch_tickers,
)
from fdre.ingestion.xbrl import ingest_company_facts

try:
    from scripts.ingestion_lock import serialized_ingestion
except ModuleNotFoundError:  # pragma: no cover - supports direct script execution
    from ingestion_lock import serialized_ingestion


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest SEC Company Facts for a bounded ticker batch"
    )
    parser.add_argument(
        "--universe",
        choices=["megacap", "research50", "sp500", "indexed"],
        default="research50",
        help="Ticker universe to ingest",
    )
    parser.add_argument("--tickers", nargs="+", help="Explicit tickers (overrides universe)")
    parser.add_argument("--offset", type=int, default=0, help="Batch offset")
    parser.add_argument("--limit", type=int, default=10, help="Batch size")
    parser.add_argument(
        "--skip-if-locked",
        action="store_true",
        help="Exit successfully when another Postgres ingestion already holds the lock",
    )
    return parser.parse_args()


def selected_tickers(args: argparse.Namespace, session: Session) -> list[str]:
    if args.tickers:
        return [ticker.upper() for ticker in args.tickers]
    if args.limit < 1:
        raise ValueError("limit must be at least 1")
    if args.offset < 0:
        raise ValueError("offset must be non-negative")
    if args.universe == "sp500":
        return sp500_batch_tickers(offset=args.offset, limit=args.limit)
    if args.universe == "research50":
        return list(RESEARCH_UNIVERSE_TICKERS[args.offset : args.offset + args.limit])
    if args.universe == "indexed":
        return list(
            session.scalars(
                select(Company.ticker)
                .where(Company.documents.any())
                .order_by(Company.ticker)
                .offset(args.offset)
                .limit(args.limit)
            )
        )
    return list(DEFAULT_SAMPLE_TICKERS[args.offset : args.offset + args.limit])


def main() -> None:
    args = parse_args()
    engine = create_db_engine()
    with serialized_ingestion(engine, skip_if_locked=args.skip_if_locked) as acquired:
        if not acquired:
            return
        _run_company_facts_batch(args, engine)


def _run_company_facts_batch(args: argparse.Namespace, engine: Engine) -> None:
    run_key = uuid4().hex
    with Session(engine) as session:
        tickers = selected_tickers(args, session)
        if not tickers:
            print({"status": "empty_batch", "offset": args.offset, "limit": args.limit})
            return
        before = _snapshot(session, tickers)
        start_ingestion_run(
            session,
            run_key=run_key,
            pipeline="company_facts_batch",
            config={
                "universe": args.universe,
                "tickers": tickers,
                "offset": args.offset,
                "limit": args.limit,
            },
        )

    started = perf_counter()
    status = "completed"
    stage_counts: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    try:
        with Session(engine) as session, SECClient.from_settings() as client:
            summary = ingest_company_facts(session, client, tickers=tickers)
            stage_counts["company_facts"] = {
                "status": "completed",
                "companies": summary.companies,
                "facts_seen": summary.facts_seen,
                "facts_stored": summary.facts_stored,
                "facts_skipped_without_document": summary.facts_skipped_without_document,
            }
    except Exception as error:
        status = "failed"
        failures.append(
            {
                "type": type(error).__name__,
                "message": str(error)[-4000:],
            }
        )
        raise
    finally:
        with Session(engine) as session:
            after = _snapshot(session, tickers)
            stage_counts["totals"] = {
                **after,
                "new_facts": after["facts"] - before["facts"],
                "new_canonical_facts": after["canonical_facts"] - before["canonical_facts"],
            }
            finish_ingestion_run(
                session,
                run_key=run_key,
                status=status,
                stage_counts=stage_counts,
                failures=failures,
                retry_count=0,
                latency_ms=round((perf_counter() - started) * 1000),
                provider_usage={
                    "provider": "sec_company_facts",
                    "new_facts": stage_counts["totals"]["new_facts"],
                },
                estimated_cost_usd=Decimal(0),
            )
    print(
        {
            "status": status,
            "universe": args.universe,
            "tickers": tickers,
            "offset": args.offset,
            "limit": args.limit,
            "run_key": run_key,
        },
        flush=True,
    )


def _snapshot(session: Session, tickers: list[str]) -> dict[str, int]:
    ticker_filter = FinancialFact.ticker.in_(tickers)
    facts = session.scalar(
        select(func.count()).select_from(FinancialFact).where(ticker_filter)
    ) or 0
    canonical_facts = session.scalar(
        select(func.count())
        .select_from(FinancialFact)
        .where(ticker_filter, FinancialFact.canonical_metric.is_not(None))
    ) or 0
    return {
        "facts": int(facts),
        "canonical_facts": int(canonical_facts),
    }


if __name__ == "__main__":
    main()
