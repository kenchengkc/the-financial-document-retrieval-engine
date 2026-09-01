"""Create or verify the reproducible historical market-data cache manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

from fdre.research.market_data import (
    verify_market_cache_manifest,
    write_market_cache_manifest,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache/market"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/processed/market-cache/manifest.json"),
    )
    parser.add_argument("--verify", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = (
        verify_market_cache_manifest(args.cache_dir, args.manifest)
        if args.verify
        else write_market_cache_manifest(args.cache_dir, args.manifest)
    )
    print(
        {
            "status": "verified" if args.verify else "written",
            "manifest_id": manifest.manifest_id,
            "entry_count": len(manifest.entries),
            "manifest": str(args.manifest),
        }
    )


if __name__ == "__main__":
    main()
