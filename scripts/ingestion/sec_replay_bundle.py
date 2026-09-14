from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from fdre.ingestion.sec_replay_bundle import (
    build_sec_replay_bundle,
    sec_replay_bundle_sha256,
    verify_sec_replay_bundle,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or verify deterministic offline SEC raw-parser replay bundles."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build",
        help="Freeze retained exact SEC bytes after verifying persisted parser provenance.",
    )
    build.add_argument("--accessions", nargs="+", required=True)
    build.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser(
        "verify",
        help="Verify raw hashes and re-run parsers from an existing bundle without network access.",
    )
    verify.add_argument("--bundle", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "build":
        with Session(create_db_engine()) as session:
            manifest = build_sec_replay_bundle(
                session,
                accession_numbers=args.accessions,
                destination=args.output,
            )
        bundle_path = args.output
    else:
        bundle_path = args.bundle
        manifest = verify_sec_replay_bundle(bundle_path)

    print(
        json.dumps(
            {
                "bundle_id": manifest.bundle_id,
                "bundle_sha256": sec_replay_bundle_sha256(bundle_path),
                "document_count": len(manifest.entries),
                "bundle_path": str(bundle_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
