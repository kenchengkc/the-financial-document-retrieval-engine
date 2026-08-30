"""Query and export a point-in-time Historical Universe snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fdre.universe import snapshot_to_dict, universe, write_universe_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Query a point-in-time FDRE universe snapshot.")
    parser.add_argument("universe_code")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--database-url")
    parser.add_argument("--include-provisional", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("json", "parquet"))
    args = parser.parse_args()

    snapshot = universe(
        args.universe_code,
        as_of=args.as_of,
        include_provisional=args.include_provisional,
        database_url=args.database_url,
    )
    if args.output is not None:
        write_universe_snapshot(snapshot, args.output, export_format=args.format)
    print(json.dumps(snapshot_to_dict(snapshot), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
