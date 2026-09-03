from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_engine
from apps.api.app.models import ResearchMetricSnapshot
from apps.api.app.services.operations_service import refresh_research_console_snapshots

REQUIRED_SNAPSHOT_KEYS = {
    "research-console:companies",
    "research-console:coverage",
    "research-console:quality:150",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--if-missing",
        action="store_true",
        help="Skip the full corpus audit when all production snapshots already exist.",
    )
    args = parser.parse_args()
    with Session(get_engine()) as session:
        if args.if_missing and _has_complete_snapshot(session):
            print({"status": "skipped", "reason": "snapshots already exist"})
            return
        report = refresh_research_console_snapshots(session)
    print(
        {
            "status": "completed",
            "generated_at": report.generated_at.isoformat(),
            "companies": report.company_count,
            "documents": report.document_count,
            "chunks": report.chunk_count,
        }
    )


def _has_complete_snapshot(session: Session) -> bool:
    keys = set(
        session.scalars(
            select(ResearchMetricSnapshot.metric_key).where(
                ResearchMetricSnapshot.metric_key.in_(REQUIRED_SNAPSHOT_KEYS)
            )
        )
    )
    return keys == REQUIRED_SNAPSHOT_KEYS


if __name__ == "__main__":
    main()
