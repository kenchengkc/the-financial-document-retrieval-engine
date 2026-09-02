"""Measure exact ticker-interval lineage resolution against production HU-2 evidence."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models.companies import Company
from apps.api.app.models.historical_universe import Security, SecurityIdentityPeriod
from fdre.research.historical_universe import SecurityIdentityRecord
from fdre.research.historical_universe_evidence import MembershipEvidence, SnpHistoryCsvAdapter
from fdre.research.historical_universe_identity import (
    SecCikLookupAdapter,
    SecCikNameIndex,
    load_stable_securities,
)
from fdre.research.historical_universe_lineage import (
    TickerMembershipLineageAdapter,
    resolve_evidence_via_ticker_lineage,
)
from fdre.research.historical_universe_pipeline import run_hu2_reconstruction
from fdre.research.historical_universe_sources import WikipediaHistoricalComponentsAdapter

_SCHEMA_VERSION = "fdre-hu2-ticker-lineage-audit-v1"
_TARGET_START = date(2010, 1, 1)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include timezone")
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
    rows = [
        *SnpHistoryCsvAdapter(source_url=snp_url).load(snp_history, observed_at=observed_at),
        *WikipediaHistoricalComponentsAdapter(source_url=wiki_url).load(
            wikipedia_html,
            observed_at=observed_at,
        ),
    ]
    return tuple(sorted(rows, key=lambda item: item.evidence_id))


def _load_identities(session: Session) -> tuple[SecurityIdentityRecord, ...]:
    rows = session.execute(
        select(
            SecurityIdentityPeriod.security_id,
            Company.cik,
            SecurityIdentityPeriod.symbol,
            SecurityIdentityPeriod.name,
            SecurityIdentityPeriod.exchange,
            SecurityIdentityPeriod.effective_from,
            SecurityIdentityPeriod.effective_to,
            SecurityIdentityPeriod.source_hash,
            SecurityIdentityPeriod.verification_status,
            SecurityIdentityPeriod.confidence,
        )
        .join(Security, Security.id == SecurityIdentityPeriod.security_id)
        .join(Company, Company.id == Security.company_id)
        .order_by(SecurityIdentityPeriod.security_id, SecurityIdentityPeriod.effective_from)
    ).all()
    return tuple(
        SecurityIdentityRecord(
            security_id=int(row.security_id),
            cik=str(row.cik),
            symbol=str(row.symbol),
            name=str(row.name) if row.name is not None else None,
            exchange=str(row.exchange) if row.exchange is not None else None,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            source_hash=str(row.source_hash),
            verification_status=str(row.verification_status),  # type: ignore[arg-type]
            confidence=float(row.confidence),
        )
        for row in rows
    )


def build_lineage_audit(
    *,
    evidence: tuple[MembershipEvidence, ...],
    lineages_path: Path,
    lineages_ref: str,
    sec_index: SecCikNameIndex,
    identities: tuple[SecurityIdentityRecord, ...],
    securities: tuple[object, ...],
    existing_company_ciks: set[str],
) -> dict[str, object]:
    lineages = TickerMembershipLineageAdapter(source_ref=lineages_ref).load(lineages_path)
    baseline = run_hu2_reconstruction(
        evidence,
        identities=identities,
        issuer_index=sec_index,
        securities=securities,  # type: ignore[arg-type]
    )
    lineage_resolutions = resolve_evidence_via_ticker_lineage(
        evidence,
        lineages=lineages,
        sec_index=sec_index,
        current_identities=identities,
    )
    baseline_by_id = {
        resolution.evidence_id: resolution for resolution in baseline.resolutions
    }
    lineage_by_id = {resolution.evidence_id: resolution for resolution in lineage_resolutions}

    target = tuple(record for record in evidence if record.effective_at >= _TARGET_START)
    counters: Counter[str] = Counter()
    projected_ciks: set[str] = set()
    projected_lineages: set[str] = set()
    projected_missing_company_ciks: set[str] = set()
    residual: list[dict[str, object]] = []
    for record in target:
        base = baseline_by_id[record.evidence_id]
        lineage = lineage_by_id[record.evidence_id]
        if base.status == "resolved":
            counters["baseline_resolved"] += 1
            counters["projected_resolved"] += 1
            continue
        if lineage.status == "resolved" and lineage.cik is not None:
            counters["lineage_recovered"] += 1
            counters["projected_resolved"] += 1
            projected_ciks.add(lineage.cik)
            if lineage.lineage_id is not None:
                projected_lineages.add(lineage.lineage_id)
            if lineage.cik not in existing_company_ciks:
                projected_missing_company_ciks.add(lineage.cik)
            continue
        counters[f"lineage_{lineage.status}"] += 1
        residual.append(
            {
                "evidence_id": record.evidence_id,
                "effective_at": record.effective_at.isoformat(),
                "event_type": record.event_type,
                "raw_symbol": record.raw_symbol,
                "raw_name": record.raw_name,
                "baseline_status": base.status,
                "baseline_reason": base.reason,
                "lineage_status": lineage.status,
                "lineage_reason": lineage.reason,
                "lineage_candidate_ciks": list(lineage.candidate_ciks),
            }
        )

    target_count = len(target)
    projected_resolved = counters["projected_resolved"]
    return {
        "schema_version": _SCHEMA_VERSION,
        "target_start": _TARGET_START.isoformat(),
        "target_evidence_count": target_count,
        "ticker_lineage_interval_count": len(lineages),
        "baseline_resolved_count": counters["baseline_resolved"],
        "lineage_recovered_count": counters["lineage_recovered"],
        "projected_resolved_count": projected_resolved,
        "projected_resolution_rate": round(
            projected_resolved / target_count if target_count else 0.0,
            6,
        ),
        "projected_unique_cik_count": len(projected_ciks),
        "projected_unique_lineage_count": len(projected_lineages),
        "projected_missing_company_cik_count": len(projected_missing_company_ciks),
        "lineage_status_counts_for_baseline_failures": {
            key.removeprefix("lineage_"): value
            for key, value in sorted(counters.items())
            if key.startswith("lineage_") and key != "lineage_recovered"
        },
        "residual_count": len(residual),
        "residual": residual,
        "interpretation": (
            "Projected resolution counts a row only when the existing HU-2 resolver already "
            "resolves it or the independent complete-history source maps the exact raw event "
            "boundary to one ticker interval whose SEC/R1/current-identity CIK support is unique. "
            "It assumes a dedicated provisional stable security can be created for each newly "
            "supported historical interval; no historical write is performed by this audit."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure HU-2 ticker-lineage recovery.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--snp-history", required=True, type=Path)
    parser.add_argument("--wikipedia-html", required=True, type=Path)
    parser.add_argument("--sec-cik-lookup", required=True, type=Path)
    parser.add_argument("--ticker-lineages", required=True, type=Path)
    parser.add_argument("--ticker-lineages-ref", required=True)
    parser.add_argument("--observed-at", type=_parse_timestamp)
    parser.add_argument("--snp-history-ref")
    parser.add_argument("--wikipedia-revision")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    observed_at = args.observed_at or datetime.now(UTC)
    evidence = _load_evidence(
        snp_history=args.snp_history,
        wikipedia_html=args.wikipedia_html,
        observed_at=observed_at,
        snp_history_ref=args.snp_history_ref,
        wikipedia_revision=args.wikipedia_revision,
    )
    names = tuple(record.raw_name for record in evidence if record.raw_name)
    sec_rows = SecCikLookupAdapter().load(
        args.sec_cik_lookup,
        observed_at=observed_at,
        restrict_to_names=names,
    )
    sec_index = SecCikNameIndex(sec_rows)
    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            identities = _load_identities(session)
            securities = load_stable_securities(session)
            company_ciks = {str(cik) for cik in session.scalars(select(Company.cik))}
    finally:
        engine.dispose()
    report = build_lineage_audit(
        evidence=evidence,
        lineages_path=args.ticker_lineages,
        lineages_ref=args.ticker_lineages_ref,
        sec_index=sec_index,
        identities=identities,
        securities=securities,
        existing_company_ciks=company_ciks,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
