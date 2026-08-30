"""Run a read-only HU-2 coverage audit against real source copies and the FDRE database."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models.companies import Company
from apps.api.app.models.historical_universe import Security, SecurityIdentityPeriod
from fdre.research.historical_universe import SecurityIdentityRecord, VerificationStatus
from fdre.research.historical_universe_evidence import MembershipEvidence, SnpHistoryCsvAdapter
from fdre.research.historical_universe_identity import (
    SecCikLookupAdapter,
    SecCikNameIndex,
    load_stable_securities,
    normalize_cik,
)
from fdre.research.historical_universe_pipeline import (
    HistoricalUniverseReconstructionResult,
    run_hu2_reconstruction,
)
from fdre.research.historical_universe_sources import WikipediaHistoricalComponentsAdapter


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone offset")
    return parsed


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_identity_records(session: Session) -> tuple[SecurityIdentityRecord, ...]:
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
        .order_by(
            SecurityIdentityPeriod.security_id,
            SecurityIdentityPeriod.effective_from,
            SecurityIdentityPeriod.id,
        )
    ).all()
    return tuple(
        SecurityIdentityRecord(
            security_id=int(security_id),
            cik=normalize_cik(str(cik)),
            symbol=str(symbol),
            name=str(name) if name is not None else None,
            exchange=str(exchange) if exchange is not None else None,
            effective_from=effective_from,
            effective_to=effective_to,
            source_hash=str(source_hash),
            verification_status=cast(VerificationStatus, str(verification_status)),
            confidence=float(confidence),
        )
        for (
            security_id,
            cik,
            symbol,
            name,
            exchange,
            effective_from,
            effective_to,
            source_hash,
            verification_status,
            confidence,
        ) in rows
    )


def _load_sources(
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
    snp_adapter = SnpHistoryCsvAdapter(source_url=snp_url)
    wiki_adapter = WikipediaHistoricalComponentsAdapter(source_url=wiki_url)
    records = [
        *snp_adapter.load(snp_history, observed_at=observed_at),
        *wiki_adapter.load(wikipedia_html, observed_at=observed_at),
    ]
    return tuple(sorted(records, key=lambda item: item.evidence_id))


def _yearly_resolution_rows(
    evidence: Sequence[MembershipEvidence],
    result: HistoricalUniverseReconstructionResult,
) -> list[dict[str, object]]:
    counts_by_year: dict[int, Counter[str]] = defaultdict(Counter)
    ordered_evidence = tuple(sorted(evidence, key=lambda item: item.evidence_id))
    for record, resolution, issuer_resolution in zip(
        ordered_evidence,
        result.resolutions,
        result.issuer_resolutions,
        strict=True,
    ):
        counts = counts_by_year[record.effective_at.year]
        counts["evidence"] += 1
        counts[f"security_{resolution.status}"] += 1
        issuer_status = (
            issuer_resolution.status if issuer_resolution is not None else "not_attempted"
        )
        counts[f"issuer_{issuer_status}"] += 1
        counts[f"source_{record.source}"] += 1
    for event in result.events:
        counts_by_year[event.effective_at.year][f"event_{event.verification_status}"] += 1
    for membership in result.memberships:
        counts_by_year[membership.effective_from.year][
            f"interval_{membership.verification_status}"
        ] += 1
    return [
        {"year": year, **dict(sorted(counts.items()))}
        for year, counts in sorted(counts_by_year.items())
    ]


def _source_manifest(
    *,
    observed_at: datetime,
    snp_history: Path,
    wikipedia_html: Path,
    sec_cik_lookup: Path,
    snp_history_ref: str | None,
    wikipedia_revision: str | None,
) -> dict[str, object]:
    return {
        "observed_at": observed_at.isoformat(),
        "sources": {
            "snp_history": {
                "path": snp_history.name,
                "sha256": _sha256_file(snp_history),
                "git_ref": snp_history_ref,
            },
            "wikipedia_historical_components": {
                "path": wikipedia_html.name,
                "sha256": _sha256_file(wikipedia_html),
                "revision": wikipedia_revision,
                "title": "Historical components of the S&P 500",
            },
            "sec_cik_lookup": {
                "path": sec_cik_lookup.name,
                "sha256": _sha256_file(sec_cik_lookup),
            },
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a read-only Historical Universe HU-2 audit."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--snp-history", required=True, type=Path)
    parser.add_argument("--wikipedia-html", required=True, type=Path)
    parser.add_argument("--sec-cik-lookup", required=True, type=Path)
    parser.add_argument("--observed-at", type=_parse_timestamp)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--snp-history-ref")
    parser.add_argument("--wikipedia-revision")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    observed_at: datetime = args.observed_at or datetime.now(UTC)
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    evidence = _load_sources(
        snp_history=args.snp_history,
        wikipedia_html=args.wikipedia_html,
        observed_at=observed_at,
        snp_history_ref=args.snp_history_ref,
        wikipedia_revision=args.wikipedia_revision,
    )
    relevant_names = tuple(record.raw_name for record in evidence if record.raw_name)
    issuer_evidence = SecCikLookupAdapter().load(
        args.sec_cik_lookup,
        observed_at=observed_at,
        restrict_to_names=relevant_names,
    )
    issuer_index = SecCikNameIndex(issuer_evidence)

    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            company_count = int(session.scalar(select(func.count(Company.id))) or 0)
            identities = _load_identity_records(session)
            securities = load_stable_securities(session)
        result = run_hu2_reconstruction(
            evidence,
            identities=identities,
            issuer_index=issuer_index,
            securities=securities,
        )
    finally:
        engine.dispose()

    ordered_evidence = tuple(sorted(evidence, key=lambda item: item.evidence_id))
    unresolved: list[dict[str, object]] = []
    for evidence_record, resolution, issuer_resolution in zip(
        ordered_evidence,
        result.resolutions,
        result.issuer_resolutions,
        strict=True,
    ):
        if resolution.status == "resolved":
            continue
        row: dict[str, object] = {
            "evidence_id": evidence_record.evidence_id,
            "source": evidence_record.source,
            "effective_at": evidence_record.effective_at.isoformat(),
            "event_type": evidence_record.event_type,
            "raw_symbol": evidence_record.raw_symbol,
            "raw_name": evidence_record.raw_name,
            "resolution_status": resolution.status,
            "resolution_method": resolution.method,
            "reason": resolution.reason,
            "candidate_security_ids": list(resolution.candidate_security_ids),
        }
        if issuer_resolution is not None:
            row.update(
                {
                    "issuer_resolution_status": issuer_resolution.status,
                    "issuer_cik": issuer_resolution.cik,
                    "issuer_candidate_ciks": list(issuer_resolution.candidate_ciks),
                    "issuer_reason": issuer_resolution.reason,
                }
            )
        else:
            row["issuer_resolution_status"] = "not_attempted"
        unresolved.append(row)
    coverage_start = (
        result.audit.coverage_start.isoformat() if result.audit.coverage_start else None
    )
    coverage_end = result.audit.coverage_end.isoformat() if result.audit.coverage_end else None
    report = {
        "schema_version": "fdre-hu2-production-coverage-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "audit_id": result.audit.audit_id,
        "universe_code": result.audit.universe_code,
        "evidence_count": result.audit.evidence_count,
        "source_count": result.audit.source_count,
        "source_evidence_counts": dict(
            sorted(Counter(record.source for record in ordered_evidence).items())
        ),
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "issuer_name_evidence_count": len(issuer_evidence),
        "issuer_name_count": issuer_index.name_count,
        "issuer_resolution_counts": dict(result.audit.issuer_resolution_counts),
        "production_company_count": company_count,
        "security_identity_record_count": len(identities),
        "stable_security_count": len(securities),
        "stable_common_stock_security_count": sum(
            security.security_type == "common_stock" for security in securities
        ),
        "stable_security_cik_count": len({security.cik for security in securities}),
        "security_resolution_counts": dict(result.audit.security_resolution_counts),
        "security_resolution_method_counts": dict(
            result.audit.security_resolution_method_counts
        ),
        "verified_event_count": result.audit.verified_event_count,
        "provisional_event_count": result.audit.provisional_event_count,
        "conflict_event_count": result.audit.conflict_event_count,
        "materialized_interval_count": result.audit.materialized_interval_count,
        "verified_interval_count": result.audit.verified_interval_count,
        "provisional_interval_count": result.audit.provisional_interval_count,
        "materialization_issue_counts": dict(result.audit.materialization_issue_counts),
        "unresolved_or_ambiguous_count": len(unresolved),
        "resolution_failure_reason_counts": dict(
            sorted(Counter(str(row["reason"]) for row in unresolved).items())
        ),
        "promoted_membership_count": 0,
    }
    manifest = _source_manifest(
        observed_at=observed_at,
        snp_history=args.snp_history,
        wikipedia_html=args.wikipedia_html,
        sec_cik_lookup=args.sec_cik_lookup,
        snp_history_ref=args.snp_history_ref,
        wikipedia_revision=args.wikipedia_revision,
    )

    (output_dir / "coverage.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "source-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "unresolved.json").write_text(
        json.dumps(unresolved, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "yearly.json").write_text(
        json.dumps(_yearly_resolution_rows(evidence, result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
