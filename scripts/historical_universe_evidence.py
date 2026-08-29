"""Normalize and audit Historical Universe evidence into deterministic local artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from fdre.research.historical_universe_evidence import MembershipEvidence, SnpHistoryCsvAdapter
from fdre.research.historical_universe_identity import (
    SecCikLookupAdapter,
    SecCikNameIndex,
    resolve_issuer_name,
)
from fdre.research.historical_universe_sources import WikipediaHistoricalComponentsAdapter


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
            "membership. Optionally audit exact issuer-name matches against a local SEC cumulative "
            "CIK lookup. No network access is performed."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Local source file. Upstream datasets are not bundled by FDRE.",
    )
    parser.add_argument(
        "--adapter",
        choices=("snp-history-csv", "wikipedia-historical-components-html"),
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
    parser.add_argument(
        "--sec-cik-lookup",
        type=Path,
        help=(
            "Optional local SEC cik-lookup-data.txt. Only names present in the membership batch "
            "are retained in memory; exact normalized matches are audited but do not mutate raw "
            "source evidence."
        ),
    )
    return parser


def _load_membership_evidence(args: argparse.Namespace) -> tuple[MembershipEvidence, ...]:
    if args.adapter == "snp-history-csv":
        adapter = SnpHistoryCsvAdapter(universe_code=args.universe)
        return adapter.load(args.input, observed_at=args.observed_at)
    if args.adapter == "wikipedia-historical-components-html":
        adapter = WikipediaHistoricalComponentsAdapter(universe_code=args.universe)
        return adapter.load(args.input, observed_at=args.observed_at)
    raise ValueError(f"unsupported adapter: {args.adapter}")


def _issuer_audit(
    records: tuple[MembershipEvidence, ...],
    *,
    sec_cik_lookup: Path,
    observed_at: datetime,
) -> dict[str, object]:
    names = tuple(record.raw_name for record in records if record.raw_name)
    sec_records = SecCikLookupAdapter().load(
        sec_cik_lookup,
        observed_at=observed_at,
        restrict_to_names=names,
    )
    index = SecCikNameIndex(sec_records)
    resolutions = [resolve_issuer_name(record.raw_name, index) for record in records]
    status_counts = Counter(resolution.status for resolution in resolutions)
    ambiguous_ciks = sorted(
        {
            cik
            for resolution in resolutions
            if resolution.status == "ambiguous"
            for cik in resolution.candidate_ciks
        }
    )
    return {
        "sec_cik_lookup_match_record_count": len(sec_records),
        "sec_cik_lookup_matched_name_count": index.name_count,
        "issuer_name_resolved_count": status_counts["resolved"],
        "issuer_name_ambiguous_count": status_counts["ambiguous"],
        "issuer_name_unresolved_count": status_counts["unresolved"],
        "issuer_ambiguous_candidate_ciks": ambiguous_ciks,
    }


def main() -> int:
    args = build_parser().parse_args()
    records = _load_membership_evidence(args)
    counts = Counter(record.event_type for record in records)
    dates = sorted(record.effective_at for record in records)
    source_names = sorted({record.source for record in records})
    summary: dict[str, object] = {
        "adapter": args.adapter,
        "sources": source_names,
        "universe_code": args.universe.strip().lower(),
        "evidence_count": len(records),
        "addition_count": counts["addition"],
        "removal_count": counts["removal"],
        "coverage_start": dates[0].isoformat() if dates else None,
        "coverage_end": dates[-1].isoformat() if dates else None,
        "batch_hash": _batch_hash(records),
        "promoted_membership_count": 0,
    }

    if args.sec_cik_lookup:
        summary.update(
            _issuer_audit(
                records,
                sec_cik_lookup=args.sec_cik_lookup,
                observed_at=args.observed_at,
            )
        )

    if args.output:
        _write_jsonl(args.output, records)
        summary["output"] = str(args.output)

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
