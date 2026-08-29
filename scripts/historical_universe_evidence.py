"""Normalize Historical Universe source evidence into deterministic local artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from fdre.research.historical_universe_evidence import MembershipEvidence, SnpHistoryCsvAdapter


def _parse_observed_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--observed-at must include a timezone offset")
    return parsed


def _evidence_dict(record: MembershipEvidence) -> dict[str, object]:
    return {
        "evidence_id": record.evidence_id,
        "universe_code": record.universe_code.strip().lower(),
        "event_type": record.event_type,
        "effective_at": record.effective_at.isoformat(),
        "announced_at": record.announced_at.isoformat() if record.announced_at else None,
        "effective_session": record.effective_session,
        "raw_symbol": record.raw_symbol,
        "raw_name": record.raw_name,
        "raw_cik": record.raw_cik,
        "source": record.source,
        "source_url": record.source_url,
        "source_record_id": record.source_record_id,
        "source_observed_at": record.source_observed_at.isoformat(),
        "source_record_hash": record.source_record_hash,
        "metadata": dict(record.metadata),
    }


def _batch_hash(records: tuple[MembershipEvidence, ...]) -> str:
    payload = "\n".join(sorted(record.evidence_id for record in records)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_jsonl(path: Path, records: tuple[MembershipEvidence, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in sorted(
            records,
            key=lambda item: (
                item.effective_at,
                item.event_type,
                item.raw_symbol,
                item.evidence_id,
            ),
        ):
            handle.write(json.dumps(_evidence_dict(record), sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize a local historical-universe source file without promoting it to verified "
            "membership. No network access is performed."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Local source file. The upstream dataset is not bundled by FDRE.",
    )
    parser.add_argument(
        "--adapter",
        choices=("snp-history-csv",),
        default="snp-history-csv",
    )
    parser.add_argument(
        "--observed-at",
        required=True,
        type=_parse_observed_at,
        help="Timezone-aware timestamp when this exact local source copy was observed.",
    )
    parser.add_argument("--universe", default="sp500")
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.adapter != "snp-history-csv":
        raise ValueError(f"unsupported adapter: {args.adapter}")

    adapter = SnpHistoryCsvAdapter(universe_code=args.universe)
    records = adapter.load(args.input, observed_at=args.observed_at)
    counts = Counter(record.event_type for record in records)
    dates = sorted(record.effective_at for record in records)
    summary = {
        "adapter": args.adapter,
        "source": adapter.source_name,
        "universe_code": args.universe.strip().lower(),
        "evidence_count": len(records),
        "addition_count": counts["addition"],
        "removal_count": counts["removal"],
        "coverage_start": dates[0].isoformat() if dates else None,
        "coverage_end": dates[-1].isoformat() if dates else None,
        "batch_hash": _batch_hash(records),
        "promoted_membership_count": 0,
    }

    if args.output:
        _write_jsonl(args.output, records)
        summary["output"] = str(args.output)

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
