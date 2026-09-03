"""Run a read-only HU-2 coverage audit against real source copies and the FDRE database."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime
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
    normalize_issuer_name,
)
from fdre.research.historical_universe_pipeline import (
    HistoricalUniverseReconstructionResult,
    run_hu2_reconstruction,
)
from fdre.research.historical_universe_sources import WikipediaHistoricalComponentsAdapter

_TARGET_WINDOW_START = date(2010, 1, 1)
_TARGET_SECURITY_RESOLUTION_RATE = 0.95

_MISSING_NAME_REASON = "no exact normalized SEC historical name match"
_AMBIGUOUS_NAME_REASON = "exact normalized SEC name maps to multiple CIKs"
_MISSING_SECURITY_REASON = (
    "SEC issuer resolved but no stable common-stock security exists in FDRE"
)


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


def _normalize_symbol(value: str) -> str:
    return value.strip().upper().replace(".", "-")


def _current_constituent_reconciliation(
    path: Path,
    *,
    production_tickers: Sequence[str],
    identities: Sequence[SecurityIdentityRecord],
) -> dict[str, object]:
    """Compare the committed current snapshot with issuer rows and active HU identities.

    The committed snapshot intentionally remains a present-day check. Its ticker aliases are
    issuer-ingestion mappings, not evidence that the mapped ticker was itself an index security.
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    aliases_raw = payload.get("aliases")
    primary_raw = payload.get("primary_tickers")
    missing_raw = payload.get("missing_from_catalog")
    if not isinstance(aliases_raw, dict):
        raise ValueError("current constituent snapshot aliases must be an object")
    if not isinstance(primary_raw, list) or not all(
        isinstance(item, str) for item in primary_raw
    ):
        raise ValueError("current constituent snapshot primary_tickers must be strings")
    if not isinstance(missing_raw, list) or not all(
        isinstance(item, str) for item in missing_raw
    ):
        raise ValueError("current constituent snapshot missing_from_catalog must be strings")

    alias_symbols = {_normalize_symbol(str(symbol)) for symbol in aliases_raw}
    alias_primary_tickers = {
        _normalize_symbol(str(symbol)) for symbol in aliases_raw.values()
    }
    missing_symbols = {_normalize_symbol(symbol) for symbol in missing_raw}
    constituent_symbols = alias_symbols | missing_symbols
    primary_tickers = {_normalize_symbol(symbol) for symbol in primary_raw}
    declared_constituent_count = int(payload.get("constituent_count", -1))
    declared_primary_count = int(payload.get("primary_ticker_count", -1))
    if len(constituent_symbols) != declared_constituent_count:
        raise ValueError("current constituent snapshot constituent_count is inconsistent")
    if len(primary_tickers) != declared_primary_count:
        raise ValueError("current constituent snapshot primary_ticker_count is inconsistent")
    if alias_primary_tickers != primary_tickers:
        raise ValueError("current constituent snapshot alias targets are inconsistent")

    generated_at = _parse_timestamp(str(payload["generated_at"]))
    snapshot_date = generated_at.date()
    active_security_ids_by_symbol: dict[str, set[int]] = defaultdict(set)
    for identity in identities:
        if identity.verification_status == "rejected":
            continue
        if identity.effective_from <= snapshot_date and (
            identity.effective_to is None or snapshot_date < identity.effective_to
        ):
            active_security_ids_by_symbol[_normalize_symbol(identity.symbol)].add(
                identity.security_id
            )

    uniquely_resolved_symbols = sorted(
        symbol
        for symbol in constituent_symbols
        if len(active_security_ids_by_symbol[symbol]) == 1
    )
    ambiguous_symbols = sorted(
        symbol
        for symbol in constituent_symbols
        if len(active_security_ids_by_symbol[symbol]) > 1
    )
    missing_identity_symbols = sorted(
        symbol for symbol in constituent_symbols if not active_security_ids_by_symbol[symbol]
    )
    production = {_normalize_symbol(symbol) for symbol in production_tickers}
    unresolved_catalog_symbols = missing_symbols - production
    return {
        "snapshot_source": payload.get("source"),
        "snapshot_generated_at": generated_at.isoformat(),
        "snapshot_sha256": _sha256_file(path),
        "constituent_symbol_count": len(constituent_symbols),
        "mapped_constituent_symbol_count": len(alias_symbols)
        + len(missing_symbols - unresolved_catalog_symbols),
        "missing_catalog_symbols": sorted(unresolved_catalog_symbols),
        "primary_ticker_count": len(primary_tickers),
        "production_company_ticker_count": len(production),
        "matched_primary_ticker_count": len(primary_tickers & production),
        "missing_production_primary_tickers": sorted(primary_tickers - production),
        "unexpected_production_tickers": sorted(production - primary_tickers),
        "mapped_production_seed_exact_match": production == primary_tickers,
        "unique_active_security_identity_count": len(uniquely_resolved_symbols),
        "ambiguous_active_security_identity_symbols": ambiguous_symbols,
        "missing_active_security_identity_symbols": missing_identity_symbols,
        "current_security_identity_complete": (
            len(uniquely_resolved_symbols) == len(constituent_symbols)
            and not ambiguous_symbols
        ),
        "interpretation": (
            "Current-snapshot reconciliation is a check only; it does not establish any "
            "historical membership start date."
        ),
    }


def _raw_evidence_diagnostics(
    evidence: Sequence[MembershipEvidence],
) -> dict[str, object]:
    sources_by_event_key: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    rows_by_symbol_date: dict[tuple[str, str], list[MembershipEvidence]] = defaultdict(list)
    for record in evidence:
        symbol = _normalize_symbol(record.raw_symbol)
        effective_at = record.effective_at.isoformat()
        sources_by_event_key[(effective_at, symbol, record.event_type)].add(record.source)
        rows_by_symbol_date[(effective_at, symbol)].append(record)

    cross_source_keys = [
        key for key, sources in sources_by_event_key.items() if len(sources) > 1
    ]
    opposing_keys: list[dict[str, object]] = []
    for (effective_at, symbol), records in sorted(rows_by_symbol_date.items()):
        if {record.event_type for record in records} != {"addition", "removal"}:
            continue
        opposing_keys.append(
            {
                "effective_at": effective_at,
                "raw_symbol": symbol,
                "observations": [
                    {
                        "event_type": record.event_type,
                        "raw_name": record.raw_name,
                        "source": record.source,
                    }
                    for record in sorted(
                        records,
                        key=lambda item: (item.event_type, item.source, item.evidence_id),
                    )
                ],
            }
        )
    return {
        "exact_cross_source_agreement_key_count": len(cross_source_keys),
        "exact_cross_source_agreement_evidence_count": sum(
            len(sources_by_event_key[key]) for key in cross_source_keys
        ),
        "same_date_symbol_opposing_event_key_count": len(opposing_keys),
        "same_date_symbol_opposing_event_keys": opposing_keys,
        "opposing_event_interpretation": (
            "These raw keys require corporate-action review; they are not automatically "
            "classified as source conflicts."
        ),
    }


def _build_remediation_report(
    *,
    evidence: Sequence[MembershipEvidence],
    result: HistoricalUniverseReconstructionResult,
    unresolved: Sequence[dict[str, object]],
    current_reconciliation: dict[str, object],
    deterministic_replay_match: bool,
) -> dict[str, object]:
    by_reason = Counter(str(row["reason"]) for row in unresolved)

    def rows_for(reason: str) -> list[dict[str, object]]:
        return [row for row in unresolved if row["reason"] == reason]

    missing_security = rows_for(_MISSING_SECURITY_REASON)
    missing_name = rows_for(_MISSING_NAME_REASON)
    ambiguous_name = rows_for(_AMBIGUOUS_NAME_REASON)
    target_pairs = [
        (record, resolution)
        for record, resolution in zip(
            sorted(evidence, key=lambda item: item.evidence_id),
            result.resolutions,
            strict=True,
        )
        if record.effective_at >= _TARGET_WINDOW_START
    ]
    target_resolved = sum(resolution.status == "resolved" for _, resolution in target_pairs)
    target_resolution_rate = target_resolved / len(target_pairs) if target_pairs else 0.0
    diagnostics = _raw_evidence_diagnostics(evidence)
    opposing_count = cast(int, diagnostics["same_date_symbol_opposing_event_key_count"])
    missing_active = len(
        cast(list[object], current_reconciliation["missing_active_security_identity_symbols"])
    )
    ambiguous_active = len(
        cast(
            list[object],
            current_reconciliation["ambiguous_active_security_identity_symbols"],
        )
    )
    catalog_missing = len(
        cast(list[object], current_reconciliation["missing_catalog_symbols"])
    )
    gate_requirements = [
        {
            "id": "current_constituent_catalog_complete",
            "target": 0,
            "actual": catalog_missing,
            "met": catalog_missing == 0,
        },
        {
            "id": "current_constituent_security_identities_complete",
            "target_missing": 0,
            "actual_missing": missing_active,
            "target_ambiguous": 0,
            "actual_ambiguous": ambiguous_active,
            "met": missing_active == 0 and ambiguous_active == 0,
        },
        {
            "id": "target_window_security_resolution_rate",
            "window_start": _TARGET_WINDOW_START.isoformat(),
            "target_minimum": _TARGET_SECURITY_RESOLUTION_RATE,
            "actual": round(target_resolution_rate, 6),
            "met": target_resolution_rate >= _TARGET_SECURITY_RESOLUTION_RATE,
        },
        {
            "id": "opposing_raw_event_keys_adjudicated",
            "target": 0,
            "actual": opposing_count,
            "met": opposing_count == 0,
        },
        {
            "id": "complete_target_window_anchor",
            "target_minimum": 1,
            "actual": 0,
            "met": False,
        },
        {
            "id": "deterministic_replay",
            "target": True,
            "actual": deterministic_replay_match,
            "met": deterministic_replay_match,
        },
    ]
    return {
        "schema_version": "fdre-hu2-remediation-v1",
        "audit_id": result.audit.audit_id,
        "promotion_gate_met": all(bool(item["met"]) for item in gate_requirements),
        "promotion_gate_requirements": gate_requirements,
        "target_window": {
            "start": _TARGET_WINDOW_START.isoformat(),
            "evidence_count": len(target_pairs),
            "resolved_security_count": target_resolved,
            "security_resolution_rate": round(target_resolution_rate, 6),
            "minimum_resolution_rate": _TARGET_SECURITY_RESOLUTION_RATE,
        },
        "raw_evidence_diagnostics": diagnostics,
        "queues": [
            {
                "id": "HU2-R0",
                "priority": 0,
                "name": "current security-master bootstrap",
                "evidence_rows_blocked": len(missing_security),
                "unique_resolved_ciks": len(
                    {str(row["issuer_cik"]) for row in missing_security}
                ),
                "current_symbols_missing_identity": missing_active,
                "rule": (
                    "Create one stable security per evidenced listed share class and a "
                    "present-day identity period; never infer historical membership."
                ),
            },
            {
                "id": "HU2-R1",
                "priority": 1,
                "name": "historical issuer-name alias evidence",
                "evidence_rows": len(missing_name),
                "unique_normalized_names": len(
                    {
                        normalize_issuer_name(str(row.get("raw_name") or ""))
                        for row in missing_name
                    }
                ),
                "rule": "Persist source-backed aliases; do not add fuzzy-name guesses.",
            },
            {
                "id": "HU2-R2",
                "priority": 1,
                "name": "ambiguous CIK lineage adjudication",
                "evidence_rows": len(ambiguous_name),
                "unique_normalized_names": len(
                    {
                        normalize_issuer_name(str(row.get("raw_name") or ""))
                        for row in ambiguous_name
                    }
                ),
                "rule": (
                    "Resolve reincorporations and successors with dated evidence; retain "
                    "ambiguity when effective lineage is not established."
                ),
            },
            {
                "id": "HU2-R3",
                "priority": 1,
                "name": "same-symbol corporate-action review",
                "raw_event_keys": opposing_count,
                "rule": (
                    "Classify replacements, ticker reuse, and genuine disagreement before "
                    "event reconciliation."
                ),
            },
            {
                "id": "HU2-R4",
                "priority": 2,
                "name": "target-window full-snapshot anchor",
                "complete_snapshot_anchors": 0,
                "rule": (
                    "Add a pinned, independently sourced complete constituent snapshot at or "
                    "before 2010-01-01; change records alone cannot prove the starting set."
                ),
            },
        ],
        "resolution_failure_reason_counts": dict(sorted(by_reason.items())),
    }


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
    current_constituents: Path,
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
            "current_constituents_check": {
                "path": current_constituents.name,
                "sha256": _sha256_file(current_constituents),
                "role": "present-day reconciliation check only",
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
    parser.add_argument(
        "--current-constituents",
        type=Path,
        default=Path("data/sample/sp500_tickers.json"),
    )
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
            production_tickers = tuple(
                str(ticker)
                for ticker in session.scalars(
                    select(Company.ticker)
                    .where(Company.ticker.is_not(None))
                    .order_by(Company.ticker)
                )
                if ticker is not None
            )
            identities = _load_identity_records(session)
            securities = load_stable_securities(session)
        result = run_hu2_reconstruction(
            evidence,
            identities=identities,
            issuer_index=issuer_index,
            securities=securities,
        )
        replay = run_hu2_reconstruction(
            evidence,
            identities=identities,
            issuer_index=issuer_index,
            securities=securities,
        )
    finally:
        engine.dispose()
    deterministic_replay_match = replay.audit.audit_id == result.audit.audit_id
    if not deterministic_replay_match:
        raise RuntimeError("HU-2 reconstruction audit ID changed during exact replay")

    current_reconciliation = _current_constituent_reconciliation(
        args.current_constituents,
        production_tickers=production_tickers,
        identities=identities,
    )

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
        "current_constituent_reconciliation": current_reconciliation,
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
        "deterministic_replay_match": deterministic_replay_match,
    }
    remediation = _build_remediation_report(
        evidence=evidence,
        result=result,
        unresolved=unresolved,
        current_reconciliation=current_reconciliation,
        deterministic_replay_match=deterministic_replay_match,
    )
    manifest = _source_manifest(
        observed_at=observed_at,
        snp_history=args.snp_history,
        wikipedia_html=args.wikipedia_html,
        sec_cik_lookup=args.sec_cik_lookup,
        current_constituents=args.current_constituents,
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
    (output_dir / "remediation.json").write_text(
        json.dumps(remediation, indent=2, sort_keys=True) + "\n",
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
