"""Plan conservative HU-2 historical issuer/security seeds without writing production data.

The current ``companies`` catalog is intentionally present-day. This audit identifies historical
issuer CIKs for which public S&P membership evidence is strong enough to consider a provisional
listed-security seed, while making the missing issuer-catalog dependency explicit.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models.companies import Company
from fdre.research.historical_universe_evidence import MembershipEvidence, SnpHistoryCsvAdapter
from fdre.research.historical_universe_identity import (
    DerivedIssuerAliasEvidence,
    IssuerNameEvidence,
    IssuerNameResolution,
    SecCikLookupAdapter,
    SecCikNameIndex,
    StableSecurityRecord,
    derive_cross_source_issuer_aliases,
    load_stable_securities,
    normalize_cik,
    resolve_issuer_name,
)
from fdre.research.historical_universe_sources import WikipediaHistoricalComponentsAdapter

_SCHEMA_VERSION = "fdre-hu2-historical-security-seed-plan-v1"
_DEFAULT_TARGET_START = date(2010, 1, 1)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone offset")
    return parsed


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _normalize_symbol(value: str) -> str:
    return value.strip().upper().replace(".", "-")


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


@dataclass(frozen=True, slots=True)
class _IssuerResolutionRow:
    evidence: MembershipEvidence
    resolution: IssuerNameResolution
    alias_backed: bool


def _aliases_by_target(
    aliases: tuple[DerivedIssuerAliasEvidence, ...],
) -> dict[str, tuple[IssuerNameEvidence, ...]]:
    grouped: dict[str, list[IssuerNameEvidence]] = defaultdict(list)
    for alias in aliases:
        grouped[alias.target_evidence_id].append(alias.as_issuer_name_evidence())
    return {
        evidence_id: tuple(sorted(rows, key=lambda item: item.evidence_id))
        for evidence_id, rows in grouped.items()
    }


def _resolve_issuers(
    evidence: tuple[MembershipEvidence, ...],
    *,
    sec_index: SecCikNameIndex,
    aliases: tuple[DerivedIssuerAliasEvidence, ...],
) -> tuple[_IssuerResolutionRow, ...]:
    alias_map = _aliases_by_target(aliases)
    rows: list[_IssuerResolutionRow] = []
    for record in evidence:
        direct = resolve_issuer_name(record.raw_name, sec_index)
        if direct.status != "unresolved":
            rows.append(
                _IssuerResolutionRow(
                    evidence=record,
                    resolution=direct,
                    alias_backed=False,
                )
            )
            continue
        scoped_aliases = alias_map.get(record.evidence_id, ())
        if not scoped_aliases:
            rows.append(
                _IssuerResolutionRow(
                    evidence=record,
                    resolution=direct,
                    alias_backed=False,
                )
            )
            continue
        alias_resolution = resolve_issuer_name(
            record.raw_name,
            SecCikNameIndex(scoped_aliases),
        )
        rows.append(
            _IssuerResolutionRow(
                evidence=record,
                resolution=alias_resolution,
                alias_backed=alias_resolution.status == "resolved",
            )
        )
    return tuple(rows)


def _cross_source_event_keys(
    rows: tuple[_IssuerResolutionRow, ...],
) -> tuple[tuple[date, str, str], ...]:
    grouped: dict[tuple[date, str, str], set[str]] = defaultdict(set)
    for row in rows:
        record = row.evidence
        grouped[
            (record.effective_at, record.event_type, _normalize_symbol(record.raw_symbol))
        ].add(record.source.strip())
    return tuple(sorted(key for key, sources in grouped.items() if len(sources) >= 2))


def _opposing_same_symbol_keys(
    rows: tuple[_IssuerResolutionRow, ...],
) -> tuple[tuple[date, str], ...]:
    event_types: dict[tuple[date, str], set[str]] = defaultdict(set)
    for row in rows:
        record = row.evidence
        event_types[(record.effective_at, _normalize_symbol(record.raw_symbol))].add(
            record.event_type
        )
    return tuple(sorted(key for key, values in event_types.items() if len(values) > 1))


def build_historical_security_seed_plan(
    evidence: tuple[MembershipEvidence, ...],
    *,
    sec_index: SecCikNameIndex,
    existing_company_ciks: set[str],
    stable_securities: tuple[StableSecurityRecord, ...],
    target_start: date = _DEFAULT_TARGET_START,
) -> dict[str, object]:
    """Return a deterministic, read-only plan for provisional historical security seeds.

    Candidate criteria are intentionally strict and still do not authorize a write:

    * issuer resolves uniquely through direct SEC name evidence or one evidence-scoped R1 alias;
    * the CIK has no existing stable common-stock security;
    * every issuer-resolved S&P observation for that CIK uses one normalized symbol;
    * the target window contains at least one exact event observed by two independent sources;
    * the target window contains no same-symbol same-date opposing add/remove pair.

    The report separately identifies whether the issuer CIK is absent from ``companies``. This is
    important because a missing Company row is a schema/catalog prerequisite, not permission to
    insert a synthetic current ticker.
    """

    aliases = derive_cross_source_issuer_aliases(evidence, sec_index=sec_index)
    resolutions = _resolve_issuers(evidence, sec_index=sec_index, aliases=aliases)
    resolved = tuple(
        row
        for row in resolutions
        if row.resolution.status == "resolved" and row.resolution.cik is not None
    )
    rows_by_cik: dict[str, list[_IssuerResolutionRow]] = defaultdict(list)
    for row in resolved:
        assert row.resolution.cik is not None
        rows_by_cik[row.resolution.cik].append(row)

    existing_security_ciks = {
        security.cik
        for security in stable_securities
        if security.security_type == "common_stock"
    }
    normalized_company_ciks = {normalize_cik(cik) for cik in existing_company_ciks}

    candidates: list[dict[str, object]] = []
    exclusions: Counter[str] = Counter()
    target_missing_security_rows = 0
    target_missing_security_ciks: set[str] = set()

    for cik in sorted(rows_by_cik):
        cik_rows = tuple(
            sorted(
                rows_by_cik[cik],
                key=lambda row: (row.evidence.effective_at, row.evidence.evidence_id),
            )
        )
        target_rows = tuple(row for row in cik_rows if row.evidence.effective_at >= target_start)
        if not target_rows:
            continue
        if cik in existing_security_ciks:
            exclusions["existing_stable_common_stock_security"] += 1
            continue

        target_missing_security_rows += len(target_rows)
        target_missing_security_ciks.add(cik)
        observed_symbols = tuple(
            sorted({_normalize_symbol(row.evidence.raw_symbol) for row in cik_rows})
        )
        target_cross_source_keys = _cross_source_event_keys(target_rows)
        target_opposing_keys = _opposing_same_symbol_keys(target_rows)

        reasons: list[str] = []
        if len(observed_symbols) != 1:
            reasons.append("multiple_observed_symbols")
        if not target_cross_source_keys:
            reasons.append("no_exact_two_source_target_event")
        if target_opposing_keys:
            reasons.append("opposing_same_symbol_target_event")
        if reasons:
            for reason in reasons:
                exclusions[reason] += 1
            continue

        names = tuple(
            sorted(
                {
                    row.evidence.raw_name.strip()
                    for row in cik_rows
                    if row.evidence.raw_name is not None and row.evidence.raw_name.strip()
                }
            )
        )
        sources = tuple(sorted({row.evidence.source.strip() for row in cik_rows}))
        target_sources = tuple(
            sorted({row.evidence.source.strip() for row in target_rows})
        )
        candidates.append(
            {
                "cik": cik,
                "symbol": observed_symbols[0],
                "company_row_exists": cik in normalized_company_ciks,
                "requires_historical_company_row": cik not in normalized_company_ciks,
                "full_history_resolved_evidence_count": len(cik_rows),
                "target_resolved_evidence_count": len(target_rows),
                "alias_backed_evidence_count": sum(row.alias_backed for row in cik_rows),
                "target_alias_backed_evidence_count": sum(
                    row.alias_backed for row in target_rows
                ),
                "first_observed_event_date": min(
                    row.evidence.effective_at for row in cik_rows
                ).isoformat(),
                "last_observed_event_date": max(
                    row.evidence.effective_at for row in cik_rows
                ).isoformat(),
                "sources": list(sources),
                "target_sources": list(target_sources),
                "observed_names": list(names),
                "target_exact_two_source_event_count": len(target_cross_source_keys),
                "target_exact_two_source_events": [
                    {
                        "effective_at": effective_at.isoformat(),
                        "event_type": event_type,
                        "symbol": symbol,
                    }
                    for effective_at, event_type, symbol in target_cross_source_keys
                ],
            }
        )

    candidates.sort(key=lambda row: (str(row["cik"]), str(row["symbol"])))
    candidate_target_rows = sum(
        int(row["target_resolved_evidence_count"]) for row in candidates
    )
    candidate_missing_company_count = sum(
        bool(row["requires_historical_company_row"]) for row in candidates
    )
    candidate_existing_company_count = len(candidates) - candidate_missing_company_count

    target_evidence_count = sum(record.effective_at >= target_start for record in evidence)
    issuer_status_counts = Counter(row.resolution.status for row in resolutions)
    return {
        "schema_version": _SCHEMA_VERSION,
        "target_start": target_start.isoformat(),
        "target_evidence_count": target_evidence_count,
        "issuer_resolution_counts": dict(sorted(issuer_status_counts.items())),
        "derived_alias_evidence_count": len(aliases),
        "existing_company_cik_count": len(normalized_company_ciks),
        "existing_stable_common_stock_cik_count": len(existing_security_ciks),
        "target_missing_security_resolved_issuer_evidence_count": target_missing_security_rows,
        "target_missing_security_resolved_issuer_cik_count": len(target_missing_security_ciks),
        "candidate_cik_count": len(candidates),
        "candidate_target_evidence_count": candidate_target_rows,
        "candidate_missing_company_count": candidate_missing_company_count,
        "candidate_existing_company_without_security_count": candidate_existing_company_count,
        "exclusion_cik_counts": dict(sorted(exclusions.items())),
        "write_performed": False,
        "interpretation": (
            "Read-only planning only. A candidate means the observed S&P evidence is consistent "
            "with one provisional historical common-stock security for that CIK; it does not "
            "establish a historical ticker interval, current ticker, or S&P membership interval."
        ),
        "candidates": candidates,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan evidence-backed HU-2 historical issuer/security seeds."
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--snp-history", required=True, type=Path)
    parser.add_argument("--wikipedia-html", required=True, type=Path)
    parser.add_argument("--sec-cik-lookup", required=True, type=Path)
    parser.add_argument("--observed-at", type=_parse_timestamp)
    parser.add_argument("--snp-history-ref")
    parser.add_argument("--wikipedia-revision")
    parser.add_argument("--target-start", type=_parse_date, default=_DEFAULT_TARGET_START)
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
    relevant_names = tuple(record.raw_name for record in evidence if record.raw_name)
    sec_evidence = SecCikLookupAdapter().load(
        args.sec_cik_lookup,
        observed_at=observed_at,
        restrict_to_names=relevant_names,
    )
    sec_index = SecCikNameIndex(sec_evidence)

    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            company_ciks = {
                normalize_cik(str(cik))
                for cik in session.scalars(select(Company.cik).order_by(Company.cik))
            }
            securities = load_stable_securities(session)
    finally:
        engine.dispose()

    report = build_historical_security_seed_plan(
        evidence,
        sec_index=sec_index,
        existing_company_ciks=company_ciks,
        stable_securities=securities,
        target_start=args.target_start,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
