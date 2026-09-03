"""Adjudicate every lawcal HU-2 membership boundary against pinned external sources."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from fdre.research.historical_component_history import HistoricalComponentHistoryAdapter
from fdre.research.historical_universe_boundary import BoundaryEvidenceIndex
from fdre.research.historical_universe_evidence import SnpHistoryCsvAdapter
from fdre.research.historical_universe_lineage import TickerMembershipLineageAdapter
from fdre.research.historical_universe_sources import WikipediaHistoricalComponentsAdapter

_SCHEMA_VERSION = "fdre-hu2-boundary-audit-report-v1"


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include timezone")
    return parsed


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_boundary_report(
    *,
    component_history: Path,
    component_history_ref: str,
    ticker_lineages: Path,
    ticker_lineages_ref: str,
    snp_history: Path,
    snp_history_ref: str,
    wikipedia_html: Path,
    wikipedia_revision: str,
    observed_at: datetime,
) -> dict[str, object]:
    records = HistoricalComponentHistoryAdapter(
        source_ref=component_history_ref
    ).load(component_history)
    lineages = TickerMembershipLineageAdapter(
        source_ref=ticker_lineages_ref
    ).load(ticker_lineages)
    evidence = (
        *SnpHistoryCsvAdapter(
            source_url=(
                "https://raw.githubusercontent.com/shawnlinxl/snp-history/"
                f"{snp_history_ref}/data/history.csv"
            )
        ).load(snp_history, observed_at=observed_at),
        *WikipediaHistoricalComponentsAdapter(
            source_url=(
                "https://en.wikipedia.org/w/index.php?title="
                "Historical_components_of_the_S%26P_500&oldid="
                f"{wikipedia_revision}"
            )
        ).load(wikipedia_html, observed_at=observed_at),
    )
    audit = BoundaryEvidenceIndex(evidence=evidence, lineages=lineages).audit(records)
    summary = audit.summary()
    return {
        "schema_version": _SCHEMA_VERSION,
        **summary,
        "source_manifest": {
            "component_history": {
                "ref": component_history_ref,
                "sha256": _sha256(component_history),
            },
            "ticker_lineages": {
                "ref": ticker_lineages_ref,
                "sha256": _sha256(ticker_lineages),
            },
            "snp_history": {
                "ref": snp_history_ref,
                "sha256": _sha256(snp_history),
            },
            "wikipedia": {
                "revision": wikipedia_revision,
                "sha256": _sha256(wikipedia_html),
            },
        },
        "observed_at": observed_at.isoformat(),
        "intervals": [interval.as_dict() for interval in audit.intervals],
        "production_apply_eligible": summary["post_anchor_production_ready"],
        "interpretation": (
            "Every source interval and both of its boundaries received an explicit decision. "
            "Exact lawcal dates need one exact external source; lawcal dates marked approximate "
            "need two. A later lawcal created_at is not treated as a ticker start: an exact "
            "independent addition observation can establish the historical symbol, otherwise the "
            "identity stays provisional. Unresolved rows are retained, not guessed or silently "
            "omitted."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit HU-2 interval boundaries.")
    parser.add_argument("--component-history", required=True, type=Path)
    parser.add_argument("--component-history-ref", required=True)
    parser.add_argument("--ticker-lineages", required=True, type=Path)
    parser.add_argument("--ticker-lineages-ref", required=True)
    parser.add_argument("--snp-history", required=True, type=Path)
    parser.add_argument("--snp-history-ref", required=True)
    parser.add_argument("--wikipedia-html", required=True, type=Path)
    parser.add_argument("--wikipedia-revision", required=True)
    parser.add_argument("--observed-at", type=_timestamp)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_boundary_report(
        component_history=args.component_history,
        component_history_ref=args.component_history_ref,
        ticker_lineages=args.ticker_lineages,
        ticker_lineages_ref=args.ticker_lineages_ref,
        snp_history=args.snp_history,
        snp_history_ref=args.snp_history_ref,
        wikipedia_html=args.wikipedia_html,
        wikipedia_revision=args.wikipedia_revision,
        observed_at=args.observed_at or datetime.now(UTC),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
