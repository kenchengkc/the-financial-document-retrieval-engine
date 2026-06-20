from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import IngestionRun

try:
    from scripts.ingestion_lock import ingestion_lock_is_busy
except ModuleNotFoundError:  # pragma: no cover - supports direct script execution
    from ingestion_lock import ingestion_lock_is_busy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mark old running ingestion manifests as cancelled after Actions cancellation"
    )
    parser.add_argument("--older-than-hours", type=int, default=12)
    parser.add_argument("--status", default="cancelled")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    engine = create_db_engine()
    if ingestion_lock_is_busy(engine):
        print({"status": "skipped_ingestion_lock_busy"}, flush=True)
        return

    cutoff = datetime.now(UTC) - timedelta(hours=args.older_than_hours)
    with Session(engine) as session:
        runs = list(
            session.scalars(
                select(IngestionRun)
                .where(
                    IngestionRun.status == "running",
                    IngestionRun.completed_at.is_(None),
                    IngestionRun.started_at < cutoff,
                )
                .order_by(IngestionRun.started_at)
            )
        )
        payloads = [
            {
                "run_key": run.run_key,
                "pipeline": run.pipeline,
                "started_at": run.started_at.isoformat(),
                "config": run.config_json,
            }
            for run in runs
        ]
        if args.dry_run:
            print({"status": "dry_run", "stale_runs": payloads}, flush=True)
            return

        completed_at = datetime.now(UTC)
        for run in runs:
            run.status = args.status
            run.completed_at = completed_at
            run.failures_json = [
                *run.failures_json,
                _cleanup_failure(args.status, args.older_than_hours),
            ]
            run.stage_counts_json = {
                **run.stage_counts_json,
                "operational_cleanup": {
                    "status": args.status,
                    "reason": "stale_running_manifest",
                    "completed_at": completed_at.isoformat(),
                },
            }
        session.commit()
        print(
            {
                "status": "completed",
                "updated": len(runs),
                "stale_runs": payloads,
            },
            flush=True,
        )


def _cleanup_failure(status: str, older_than_hours: int) -> dict[str, Any]:
    return {
        "type": "stale_running_manifest",
        "status": status,
        "message": (
            "Marked old running ingestion manifest after confirming the "
            f"database ingestion lock was free; threshold={older_than_hours}h."
        ),
    }


if __name__ == "__main__":
    main()
