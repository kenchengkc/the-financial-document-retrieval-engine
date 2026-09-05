from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from fdre.indexing.archive_cleanup import DEFAULT_BATCH_SIZE, run_cleanup


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Remove accidental live-retrieval chunks/embeddings from HU-4 archive "
            "documents while preserving archive documents and elements"
        )
    )
    parser.add_argument("--database-url")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--expected-plan-id",
        help="Fail before mutation unless the live cleanup plan matches this exact ID",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit bounded cleanup batches; requires FDRE_ALLOW_PROD=1",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Allow a partially completed cleanup whose remaining archive chunk/embedding "
            "counts are below the frozen baseline"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            run_cleanup(
                session,
                apply=args.apply,
                resume=args.resume,
                batch_size=args.batch_size,
                output=args.output,
                expected_plan_id=args.expected_plan_id,
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
