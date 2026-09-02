"""Emit the independently sourced complete HU-2 target-window anchor."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

from fdre.research.historical_universe_anchor import HistoricalComponentsSnapshotAdapter

_SCHEMA_VERSION = "fdre-hu2-complete-snapshot-anchor-audit-v1"
_TARGET_DATE = date(2010, 1, 1)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include timezone")
    return parsed


def build_anchor_report(
    *,
    path: Path,
    source_ref: str,
    source_url: str,
    observed_at: datetime,
) -> dict[str, object]:
    anchor = HistoricalComponentsSnapshotAdapter(
        source_ref=source_ref,
        source_url=source_url,
    ).load_latest_on_or_before(
        path,
        target_date=_TARGET_DATE,
        observed_at=observed_at,
    )
    return {
        "schema_version": _SCHEMA_VERSION,
        "anchor_id": anchor.anchor_id,
        "universe_code": anchor.universe_code,
        "target_date": _TARGET_DATE.isoformat(),
        "effective_at": anchor.effective_at.isoformat(),
        "constituent_count": anchor.constituent_count,
        "source": anchor.source,
        "source_url": anchor.source_url,
        "source_ref": anchor.source_ref,
        "source_hash": anchor.source_hash,
        "source_observed_at": anchor.source_observed_at.isoformat(),
        "duplicate_display_symbols": list(anchor.duplicate_display_symbols),
        "complete_target_window_anchor": True,
        "lineage_tokens": [item.lineage_token for item in anchor.constituents],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit the pinned HU-2 full-snapshot anchor.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--observed-at", type=_parse_timestamp)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    observed_at = args.observed_at or datetime.now(UTC)
    report = build_anchor_report(
        path=args.input,
        source_ref=args.source_ref,
        source_url=args.source_url,
        observed_at=observed_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
