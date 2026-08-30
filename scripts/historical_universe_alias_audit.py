"""Emit deterministic HU2-R1 cross-source issuer-alias evidence as a sidecar artifact."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from fdre.research.historical_universe_evidence import MembershipEvidence, SnpHistoryCsvAdapter
from fdre.research.historical_universe_identity import (
    SecCikLookupAdapter,
    SecCikNameIndex,
    derive_cross_source_issuer_aliases,
)
from fdre.research.historical_universe_sources import WikipediaHistoricalComponentsAdapter

_SCHEMA_VERSION = "fdre-hu2-cross-source-issuer-alias-audit-v1"


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone offset")
    return parsed


def _load_evidence(
    *,
    snp_history: Path,
    wikipedia_html: Path,
    observed_at: datetime,
    snp_history_ref: str | None,
    wikipedia_revision: str | None,
) -> tuple[MembershipEvidence, ...]:
    snp_url = (
        "https://raw.githubusercontent.com/shawnlinxl/snp-history/"
        f"{snp_history_ref}/data/history.csv"
        if snp_history_ref
        else None
    )
    wiki_url = (
        "https://en.wikipedia.org/w/index.php?title=Historical_components_of_the_S%26P_500"
        f"&oldid={wikipedia_revision}"
        if wikipedia_revision
        else None
    )
    records = [
        *SnpHistoryCsvAdapter(source_url=snp_url).load(
            snp_history,
            observed_at=observed_at,
        ),
        *WikipediaHistoricalComponentsAdapter(source_url=wiki_url).load(
            wikipedia_html,
            observed_at=observed_at,
        ),
    ]
    return tuple(sorted(records, key=lambda item: item.evidence_id))


def build_alias_report(
    *,
    evidence: tuple[MembershipEvidence, ...],
    sec_cik_lookup: Path,
    observed_at: datetime,
    snp_history_ref: str | None,
    wikipedia_revision: str | None,
) -> dict[str, object]:
    relevant_names = tuple(record.raw_name for record in evidence if record.raw_name)
    sec_evidence = SecCikLookupAdapter().load(
        sec_cik_lookup,
        observed_at=observed_at,
        restrict_to_names=relevant_names,
    )
    aliases = derive_cross_source_issuer_aliases(
        evidence,
        sec_index=SecCikNameIndex(sec_evidence),
    )
    aliases_by_name = Counter(alias.normalized_name for alias in aliases)
    return {
        "schema_version": _SCHEMA_VERSION,
        "observed_at": observed_at.isoformat(),
        "snp_history_ref": snp_history_ref,
        "wikipedia_revision": wikipedia_revision,
        "membership_evidence_count": len(evidence),
        "sec_name_evidence_count": len(sec_evidence),
        "derived_alias_evidence_count": len(aliases),
        "derived_alias_name_count": len(aliases_by_name),
        "repeated_alias_name_count": sum(count > 1 for count in aliases_by_name.values()),
        "derivation_rule": (
            "One-hop only: exact same universe/date/event-type/symbol across independent "
            "sources; at least one peer must resolve uniquely through the pinned SEC cumulative "
            "CIK lookup; conflicting CIK derivations are discarded; no fuzzy matching."
        ),
        "aliases": [alias.as_dict() for alias in aliases],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit the HU2-R1 issuer-alias audit artifact.")
    parser.add_argument("--snp-history", required=True, type=Path)
    parser.add_argument("--wikipedia-html", required=True, type=Path)
    parser.add_argument("--sec-cik-lookup", required=True, type=Path)
    parser.add_argument("--observed-at", type=_parse_timestamp)
    parser.add_argument("--snp-history-ref")
    parser.add_argument("--wikipedia-revision")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    observed_at: datetime = args.observed_at or datetime.now(UTC)
    evidence = _load_evidence(
        snp_history=args.snp_history,
        wikipedia_html=args.wikipedia_html,
        observed_at=observed_at,
        snp_history_ref=args.snp_history_ref,
        wikipedia_revision=args.wikipedia_revision,
    )
    report = build_alias_report(
        evidence=evidence,
        sec_cik_lookup=args.sec_cik_lookup,
        observed_at=observed_at,
        snp_history_ref=args.snp_history_ref,
        wikipedia_revision=args.wikipedia_revision,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
