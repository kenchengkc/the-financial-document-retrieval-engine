"""Measure HU-2 recovery from pinned historical S&P component CIK evidence."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from fdre.research.historical_component_history import (
    HistoricalComponentHistoryAdapter,
    HistoricalComponentIdentityIndex,
    resolve_component_identity,
)
from fdre.research.historical_universe_identity import SecCikLookupAdapter, SecCikNameIndex
from fdre.research.historical_universe_pipeline import run_hu2_reconstruction
from scripts.historical_universe_coverage import (
    _load_identity_records,
    _load_sources,
    _parse_timestamp,
)
from fdre.research.historical_universe_identity import load_stable_securities

_TARGET_START = datetime(2010, 1, 1, tzinfo=UTC).date()
_SCHEMA_VERSION = "fdre-hu2-historical-component-cik-audit-v1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure historical component CIK recovery.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--snp-history", required=True, type=Path)
    parser.add_argument("--wikipedia-html", required=True, type=Path)
    parser.add_argument("--sec-cik-lookup", required=True, type=Path)
    parser.add_argument("--component-history", required=True, type=Path)
    parser.add_argument("--component-history-ref", required=True)
    parser.add_argument("--observed-at", type=_parse_timestamp)
    parser.add_argument("--snp-history-ref")
    parser.add_argument("--wikipedia-revision")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    observed_at: datetime = args.observed_at or datetime.now(UTC)
    evidence = _load_sources(
        snp_history=args.snp_history,
        wikipedia_html=args.wikipedia_html,
        observed_at=observed_at,
        snp_history_ref=args.snp_history_ref,
        wikipedia_revision=args.wikipedia_revision,
    )
    relevant_names = tuple(record.raw_name for record in evidence if record.raw_name)
    sec_evidence = SecCikLookupAdapter().load(
        args.sec_cik_lookup,
        observed_at=observed_at,
        restrict_to_names=relevant_names,
    )
    component_records = HistoricalComponentHistoryAdapter(
        source_ref=args.component_history_ref
    ).load(args.component_history)
    component_index = HistoricalComponentIdentityIndex(component_records)

    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            identities = _load_identity_records(session)
            securities = load_stable_securities(session)
    finally:
        engine.dispose()

    baseline = run_hu2_reconstruction(
        evidence,
        identities=identities,
        issuer_index=SecCikNameIndex(sec_evidence),
        securities=securities,
    )
    ordered = tuple(sorted(evidence, key=lambda item: item.evidence_id))
    target_rows = [
        (record, resolution)
        for record, resolution in zip(ordered, baseline.resolutions, strict=True)
        if record.effective_at >= _TARGET_START
    ]

    baseline_resolved = 0
    recovered = 0
    projected_ciks: set[str] = set()
    methods: Counter[str] = Counter()
    residual_statuses: Counter[str] = Counter()
    residual: list[dict[str, object]] = []
    for record, resolution in target_rows:
        if resolution.status == "resolved":
            baseline_resolved += 1
            if resolution.cik:
                projected_ciks.add(resolution.cik)
            continue
        component = resolve_component_identity(record, component_index)
        methods[component.method] += 1
        if component.status == "resolved" and component.cik is not None:
            recovered += 1
            projected_ciks.add(component.cik)
            continue
        residual_statuses[component.status] += 1
        residual.append(
            {
                "evidence_id": record.evidence_id,
                "effective_at": record.effective_at.isoformat(),
                "event_type": record.event_type,
                "raw_symbol": record.raw_symbol,
                "raw_name": record.raw_name,
                "baseline_status": resolution.status,
                "baseline_reason": resolution.reason,
                "component_status": component.status,
                "component_method": component.method,
                "component_candidate_ciks": list(component.candidate_ciks),
                "component_reason": component.reason,
            }
        )

    projected = baseline_resolved + recovered
    denominator = len(target_rows)
    report = {
        "schema_version": _SCHEMA_VERSION,
        "target_start": _TARGET_START.isoformat(),
        "target_evidence_count": denominator,
        "baseline_resolved_count": baseline_resolved,
        "component_history_record_count": len(component_records),
        "component_history_symbol_count": component_index.symbol_count,
        "component_recovered_count": recovered,
        "component_resolution_method_counts_for_baseline_failures": dict(sorted(methods.items())),
        "projected_resolved_count": projected,
        "projected_resolution_rate": round(projected / denominator, 6) if denominator else 0.0,
        "projected_unique_cik_count": len(projected_ciks),
        "residual_count": len(residual),
        "residual_component_status_counts": dict(sorted(residual_statuses.items())),
        "interpretation": (
            "A baseline failure is projected resolved only when the pinned complete component "
            "history maps its normalized ticker to exactly one CIK across all history, or a "
            "reused ticker has exactly one CIK active at the evidence date. No company-name "
            "similarity and no fuzzy ticker matching are used. No production write occurs."
        ),
        "residual": residual,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "residual"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
