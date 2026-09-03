"""Plan, materialize, and audit the bounded HU-4 research archive."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from fdre.ingestion.sec_client import SECClient
from fdre.ingestion.sec_downloader import SECFilingDownloader
from fdre.parsing.html_filing_parser import HtmlFilingParser
from fdre.research.archive import (
    archive_report_payload,
    archive_storage_snapshot,
    export_archive_panel,
    ingest_archive_metadata,
    materialize_archive_filings,
    select_archive_issuers,
    write_archive_report,
)
from scripts.ingestion.ingestion_lock import lane_lock_id, serialized_ingestion


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a zero-embedding research archive from historical-universe issuers"
    )
    parser.add_argument("--database-url")
    parser.add_argument("--universe", default="sp500")
    parser.add_argument("--from", dest="filed_from", type=date.fromisoformat, default="2010-01-01")
    parser.add_argument("--to", dest="filed_to", type=date.fromisoformat, required=True)
    parser.add_argument("--forms", nargs="+", default=["10-K"])
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--lane", type=int, default=0)
    parser.add_argument("--limit-per-form", type=int)
    parser.add_argument(
        "--verified-only",
        action="store_true",
        help="Archive only issuers with verified overlapping memberships",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Fetch metadata and filings, parse research sections, and export Parquet",
    )
    parser.add_argument("--force-parse", action="store_true")
    parser.add_argument(
        "--skip-panel-export",
        action="store_true",
        help="Skip the optional Parquet feature artifact",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed/research-archive"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.filed_to < args.filed_from:
        raise SystemExit("--to must not precede --from")
    if args.limit < 1:
        raise SystemExit("--limit must be positive")
    if args.lane < 0:
        raise SystemExit("--lane must be non-negative")
    if args.limit_per_form is not None and args.limit_per_form < 1:
        raise SystemExit("--limit-per-form must be positive")

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"batch-{args.offset:04d}-{args.limit:04d}.json"
    panel_path = output_dir / f"panel-{args.offset:04d}-{args.limit:04d}.parquet"
    engine = create_db_engine(args.database_url)
    try:
        if not args.apply:
            _run(args, engine, report_path=report_path, panel_path=panel_path)
            return
        with serialized_ingestion(
            engine,
            skip_if_locked=False,
            lock_id=lane_lock_id(args.lane),
        ) as acquired:
            if not acquired:
                raise RuntimeError("research archive ingestion lock was not acquired")
            _run(args, engine, report_path=report_path, panel_path=panel_path)
    finally:
        engine.dispose()


def _run(
    args: argparse.Namespace,
    engine: Engine,
    *,
    report_path: Path,
    panel_path: Path,
) -> None:
    with Session(engine) as session:
        issuers = select_archive_issuers(
            session,
            universe_code=args.universe,
            period_from=args.filed_from,
            period_to=args.filed_to,
            include_provisional=not args.verified_only,
            offset=args.offset,
            limit=args.limit,
        )
        before = archive_storage_snapshot(
            session,
            issuers=issuers,
            filed_from=args.filed_from,
            filed_to=args.filed_to,
            form_types=args.forms,
        )
        if not args.apply:
            payload = archive_report_payload(
                universe_code=args.universe,
                period_from=args.filed_from,
                period_to=args.filed_to,
                issuers=issuers,
                before=before,
            )
            write_archive_report(report_path, payload)
            print(payload)
            return

        with SECClient.from_settings() as client:
            metadata = ingest_archive_metadata(
                session,
                client=client,
                issuers=issuers,
                form_types=args.forms,
                filed_from=args.filed_from,
                filed_to=args.filed_to,
                limit_per_form=args.limit_per_form,
            )
            materialization = materialize_archive_filings(
                session,
                downloader=SECFilingDownloader(client),
                parser=HtmlFilingParser(),
                issuers=issuers,
                form_types=args.forms,
                filed_from=args.filed_from,
                filed_to=args.filed_to,
                force_parse=args.force_parse,
            )
        after = archive_storage_snapshot(
            session,
            issuers=issuers,
            filed_from=args.filed_from,
            filed_to=args.filed_to,
            form_types=args.forms,
        )
        if after.embeddings != before.embeddings:
            raise RuntimeError("HU-4 archive must not create embeddings")
        panel = None
        if not args.skip_panel_export:
            panel = export_archive_panel(
                session,
                issuers=issuers,
                filed_from=args.filed_from,
                filed_to=args.filed_to,
                output_path=panel_path,
            )
        payload = archive_report_payload(
            universe_code=args.universe,
            period_from=args.filed_from,
            period_to=args.filed_to,
            issuers=issuers,
            before=before,
            after=after,
            metadata=metadata,
            materialization=materialization,
            panel=panel,
        )
        write_archive_report(report_path, payload)
        print(payload)


if __name__ == "__main__":
    main()
