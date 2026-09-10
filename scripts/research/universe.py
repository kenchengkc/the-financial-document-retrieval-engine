from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from fdre.universe import snapshot_to_dict, universe_from_session, write_universe_snapshot
from fdre.universe_diff import compare_universe_snapshots, universe_diff_to_dict

OperationEntrypoint = Callable[[], int]
_OPERATION_HELP = {
    "audit": "Run the read-only HU-2 coverage and deterministic-replay audit.",
    "reconcile": "Reconcile the complete historical-universe anchor against pinned evidence.",
    "validate": "Evaluate the final HU-2 promotion gate without mutating production state.",
    "promote": "Plan or explicitly apply guarded HU-2 production materialization.",
}


def _operation_entrypoint(command: str) -> OperationEntrypoint:
    if command == "audit":
        from scripts.research.historical_universe.historical_universe_coverage import main

        return main
    if command == "reconcile":
        from scripts.research.historical_universe.historical_universe_anchor_reconciliation import (
            main,
        )

        return main
    if command == "validate":
        from scripts.research.historical_universe.historical_universe_promotion_gate import main

        return main
    if command == "promote":
        from fdre.research.historical_universe.promotion import main

        return main
    raise ValueError(f"unknown historical-universe operation: {command}")


def _run_operation(command: str, argv: Sequence[str]) -> int:
    """Run an existing HU command without changing its parser or invocation contract."""

    entrypoint = _operation_entrypoint(command)
    previous_argv = sys.argv
    try:
        sys.argv = [f"{previous_argv[0]} {command}", *argv]
        return entrypoint()
    finally:
        sys.argv = previous_argv


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect, audit, validate, and operate FDRE point-in-time security universes.",
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

    for command, help_text in _OPERATION_HELP.items():
        subparsers.add_parser(command, help=help_text, add_help=False)

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


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] in _OPERATION_HELP:
        return _run_operation(raw_argv[0], raw_argv[1:])

    parser = _parser()
    args = parser.parse_args(raw_argv)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
