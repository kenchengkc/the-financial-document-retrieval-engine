from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from fdre.universe import snapshot_to_dict, universe_from_session, write_universe_snapshot
from fdre.universe_diff import compare_universe_snapshots, universe_diff_to_dict


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and export FDRE point-in-time security universes.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser(
        "snapshot",
        help="Materialize one deterministic point-in-time universe snapshot.",
    )
    snapshot.add_argument("universe_code")
    snapshot.add_argument("--as-of", required=True)
    snapshot.add_argument("--include-provisional", action="store_true")
    snapshot.add_argument("--database-url")
    snapshot.add_argument("--format", choices=("json", "parquet"), default="json")
    snapshot.add_argument("--output", type=Path)

    diff = subparsers.add_parser(
        "diff",
        help="Compare two snapshots by stable listed-security identity.",
    )
    diff.add_argument("universe_code")
    diff.add_argument("--from", dest="from_as_of", required=True)
    diff.add_argument("--to", dest="to_as_of", required=True)
    diff.add_argument("--include-provisional", action="store_true")
    diff.add_argument("--database-url")
    diff.add_argument("--output", type=Path)

    return parser


def _snapshot_command(session: Session, args: argparse.Namespace) -> dict[str, object]:
    snapshot = universe_from_session(
        session,
        args.universe_code,
        as_of=args.as_of,
        include_provisional=args.include_provisional,
    )
    payload = snapshot_to_dict(snapshot)
    if args.format == "parquet":
        if args.output is None:
            raise ValueError("--output is required when --format=parquet")
        write_universe_snapshot(snapshot, args.output, export_format="parquet")
    elif args.output is not None:
        write_universe_snapshot(snapshot, args.output, export_format="json")
    return payload


def _diff_command(session: Session, args: argparse.Namespace) -> dict[str, object]:
    before = universe_from_session(
        session,
        args.universe_code,
        as_of=args.from_as_of,
        include_provisional=args.include_provisional,
    )
    after = universe_from_session(
        session,
        args.universe_code,
        as_of=args.to_as_of,
        include_provisional=args.include_provisional,
    )
    payload = universe_diff_to_dict(compare_universe_snapshots(before, after))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return payload


def main(argv: Sequence[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            try:
                payload = (
                    _snapshot_command(session, args)
                    if args.command == "snapshot"
                    else _diff_command(session, args)
                )
            except ValueError as error:
                parser.error(str(error))
    finally:
        engine.dispose()

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
