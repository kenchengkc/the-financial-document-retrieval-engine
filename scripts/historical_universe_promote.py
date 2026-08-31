"""Materialize source-backed HU-2 issuer, security, identity, and membership rows.

The materializer is deliberately conservative:
- historical-only issuers use ticker=NULL rather than a synthetic current ticker;
- stable securities are keyed by exact CIK + normalized historical symbol;
- ticker identity is asserted only across periods where that exact CIK/symbol is observed as an
  S&P constituent (plus the removal boundary day needed to identify the departing security);
- membership is verified only when the independent pinned fja05680 interval exactly agrees with
  the lawcal component interval and the lawcal dates are not marked approximate;
- all other source-backed membership is persisted as provisional;
- the command is dry-run unless --apply is explicit.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import create_db_engine
from apps.api.app.models import Company
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.research.historical_component_history import (
    HistoricalComponentHistoryAdapter,
    HistoricalComponentRecord,
)
from fdre.research.historical_universe_identity import normalize_cik
from fdre.research.historical_universe_lineage import TickerMembershipLineageAdapter

_SCHEMA_VERSION = "fdre-hu2-production-materialization-v1"
_SOURCE = "lawcal/sp500-components-history"


def _symbol(value: str) -> str:
    return value.strip().upper().replace(".", "-")


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CurrentIssuer:
    symbol: str
    cik: str
    name: str
    sector: str | None


@dataclass(frozen=True, slots=True)
class MaterializationPlan:
    historical_company_creates: int
    current_company_creates: int
    current_ticker_fills: int
    security_creates: int
    identity_creates: int
    membership_creates: int
    verified_memberships: int
    provisional_memberships: int
    source_interval_count: int
    exact_independent_interval_count: int
    plan_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "historical_company_creates": self.historical_company_creates,
            "current_company_creates": self.current_company_creates,
            "current_ticker_fills": self.current_ticker_fills,
            "security_creates": self.security_creates,
            "identity_creates": self.identity_creates,
            "membership_creates": self.membership_creates,
            "verified_memberships": self.verified_memberships,
            "provisional_memberships": self.provisional_memberships,
            "source_interval_count": self.source_interval_count,
            "exact_independent_interval_count": self.exact_independent_interval_count,
            "plan_hash": self.plan_hash,
        }


def _load_current(path: Path) -> dict[str, CurrentIssuer]:
    result: dict[str, CurrentIssuer] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"symbol", "cik", "name", "sector"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("current component CSV is missing required columns")
        for row in reader:
            cik = normalize_cik(row["cik"] or "")
            issuer = CurrentIssuer(
                symbol=(row["symbol"] or "").strip().upper(),
                cik=cik,
                name=(row["name"] or "").strip(),
                sector=(row["sector"] or "").strip() or None,
            )
            if not issuer.symbol or not issuer.name:
                raise ValueError("current component row has empty symbol/name")
            previous = result.get(cik)
            if previous is None:
                result[cik] = issuer
            elif previous.symbol != issuer.symbol:
                # Multiple current share classes under one CIK are valid. Company.ticker is only
                # a convenience primary ticker, so choose the deterministic lexicographic symbol.
                result[cik] = min(previous, issuer, key=lambda value: value.symbol)
    return result


def _verified_interval_keys(
    lineage_path: Path,
    source_ref: str,
) -> set[tuple[str, date, date | None]]:
    lineages = TickerMembershipLineageAdapter(source_ref=source_ref).load(lineage_path)
    return {
        (_symbol(lineage.symbol), lineage.effective_from, lineage.effective_to)
        for lineage in lineages
    }


def _component_key(record: HistoricalComponentRecord) -> tuple[str, str]:
    return record.cik, _symbol(record.symbol)


def _membership_verified(
    record: HistoricalComponentRecord,
    verified_intervals: set[tuple[str, date, date | None]],
) -> bool:
    return (
        not record.added_approximate
        and not record.removed_approximate
        and (_symbol(record.symbol), record.effective_from, record.effective_to)
        in verified_intervals
    )


def _identity_bounds(records: list[HistoricalComponentRecord]) -> tuple[date, date | None]:
    start = min(record.effective_from for record in records)
    if any(record.effective_to is None for record in records):
        return start, None
    # Membership removal is a boundary at which the departing security is still the subject of
    # the event. Keep the identity valid on that date without claiming validity beyond it.
    end = max(record.effective_to for record in records if record.effective_to is not None)
    return start, end + timedelta(days=1)


def _source_hash_for_group(records: list[HistoricalComponentRecord]) -> str:
    return _hash(
        {
            "schema_version": _SCHEMA_VERSION,
            "record_ids": sorted(record.record_id for record in records),
        }
    )


def _existing_security_by_key(
    session: Session,
    companies_by_id: dict[int, Company],
) -> dict[tuple[str, str], Security]:
    securities = list(session.scalars(select(Security).order_by(Security.id)))
    identities = list(
        session.scalars(
            select(SecurityIdentityPeriod).order_by(SecurityIdentityPeriod.id)
        )
    )
    security_by_id = {security.id: security for security in securities}
    result: dict[tuple[str, str], Security] = {}
    ambiguous: set[tuple[str, str]] = set()
    for identity in identities:
        security = security_by_id.get(identity.security_id)
        if security is None:
            continue
        company = companies_by_id.get(security.company_id)
        if company is None:
            continue
        key = (company.cik, _symbol(identity.symbol))
        prior = result.get(key)
        if prior is None:
            result[key] = security
        elif prior.id != security.id:
            ambiguous.add(key)
    for key in ambiguous:
        result.pop(key, None)
    return result


def materialize(
    session: Session,
    *,
    records: tuple[HistoricalComponentRecord, ...],
    current_by_cik: dict[str, CurrentIssuer],
    verified_intervals: set[tuple[str, date, date | None]],
    observed_at: datetime,
    apply: bool,
) -> MaterializationPlan:
    companies = list(session.scalars(select(Company).order_by(Company.id)))
    companies_by_cik = {company.cik: company for company in companies}
    companies_by_id = {company.id: company for company in companies}
    existing_security_by_key = _existing_security_by_key(session, companies_by_id)

    grouped: dict[tuple[str, str], list[HistoricalComponentRecord]] = defaultdict(list)
    latest_by_cik: dict[str, HistoricalComponentRecord] = {}
    for record in records:
        grouped[_component_key(record)].append(record)
        prior = latest_by_cik.get(record.cik)
        if prior is None or record.effective_from > prior.effective_from:
            latest_by_cik[record.cik] = record

    historical_company_creates = 0
    current_company_creates = 0
    current_ticker_fills = 0
    security_creates = 0
    identity_creates = 0
    membership_creates = 0
    verified_memberships = 0
    provisional_memberships = 0

    # Create/fill issuer rows first so every Security continues to reference the canonical issuer
    # table while current-company APIs can exclude ticker=NULL rows.
    all_ciks = sorted({record.cik for record in records})
    for cik in all_ciks:
        company = companies_by_cik.get(cik)
        current = current_by_cik.get(cik)
        latest = latest_by_cik[cik]
        if company is None:
            if current is not None:
                current_company_creates += 1
            else:
                historical_company_creates += 1
            if apply:
                company = Company(
                    ticker=current.symbol if current is not None else None,
                    cik=cik,
                    name=current.name if current is not None else latest.name,
                    sector=current.sector if current is not None else latest.sector,
                )
                session.add(company)
                session.flush()
                companies_by_cik[cik] = company
                companies_by_id[company.id] = company
        elif current is not None and company.ticker is None:
            current_ticker_fills += 1
            if apply:
                ticker_owner = session.scalar(
                    select(Company).where(Company.ticker == current.symbol)
                )
                if ticker_owner is not None and ticker_owner.id != company.id:
                    raise ValueError(
                        f"current ticker {current.symbol} already belongs to another company"
                    )
                company.ticker = current.symbol

    # Refresh exact identity→security mapping after potential issuer creation. Existing current
    # identities are reused; otherwise one conservative security is created per exact CIK/symbol.
    if apply:
        session.flush()
    for key in sorted(grouped):
        cik, symbol = key
        source_records = sorted(
            grouped[key], key=lambda value: (value.effective_from, value.record_id)
        )
        company = companies_by_cik.get(cik)
        if company is None:
            # Dry-run has no transient Company row by design; counts are still complete.
            security = existing_security_by_key.get(key)
        else:
            security = existing_security_by_key.get(key)
        if security is None:
            security_creates += 1
            if apply:
                if company is None:
                    raise RuntimeError(f"issuer {cik} was not materialized")
                security = Security(company_id=company.id, security_type="common_stock")
                session.add(security)
                session.flush()
                existing_security_by_key[key] = security

        identity_start, identity_end = _identity_bounds(source_records)
        identity_exists = False
        if security is not None:
            existing_identities = list(
                session.scalars(
                    select(SecurityIdentityPeriod).where(
                        SecurityIdentityPeriod.security_id == security.id,
                        SecurityIdentityPeriod.symbol.in_([symbol, symbol.replace("-", ".")]),
                    )
                )
            )
            for identity in existing_identities:
                if identity.effective_from <= identity_start and (
                    identity.effective_to is None
                    or (
                        identity_end is not None
                        and identity_end <= identity.effective_to
                    )
                ):
                    identity_exists = True
                    break
            if not identity_exists and existing_identities:
                earliest = min(identity.effective_from for identity in existing_identities)
                if identity_start < earliest:
                    identity_end = min(identity_end, earliest) if identity_end else earliest
                else:
                    # An existing exact-symbol identity begins before the new source interval but
                    # did not fully cover it. Refuse to create overlapping identity claims.
                    identity_exists = True
        if not identity_exists and identity_end != identity_start:
            identity_creates += 1
            if apply:
                if security is None:
                    raise RuntimeError("security must exist before identity materialization")
                session.add(
                    SecurityIdentityPeriod(
                        security_id=security.id,
                        symbol=symbol,
                        name=source_records[-1].name,
                        exchange=None,
                        effective_from=identity_start,
                        effective_to=identity_end,
                        source=_SOURCE,
                        source_url=source_records[-1].source_ref,
                        source_observed_at=observed_at,
                        source_hash=_source_hash_for_group(source_records),
                        verification_status="verified",
                        confidence=0.98,
                    )
                )

        for record in source_records:
            is_verified = _membership_verified(record, verified_intervals)
            if is_verified:
                verified_memberships += 1
            else:
                provisional_memberships += 1
            if security is None:
                membership_creates += 1
                continue
            existing_membership = session.scalar(
                select(UniverseMembership).where(
                    UniverseMembership.universe_code == "sp500",
                    UniverseMembership.security_id == security.id,
                    UniverseMembership.effective_from == record.effective_from,
                )
            )
            if existing_membership is not None:
                if existing_membership.effective_to != record.effective_to:
                    raise ValueError(
                        f"membership boundary mismatch for {cik}/{symbol} "
                        f"at {record.effective_from}"
                    )
                continue
            membership_creates += 1
            if apply:
                source = _SOURCE
                if is_verified:
                    source += "+fja05680/sp500-ticker-start-end"
                session.add(
                    UniverseMembership(
                        universe_code="sp500",
                        security_id=security.id,
                        effective_from=record.effective_from,
                        effective_to=record.effective_to,
                        source=source,
                        source_url=record.source_ref,
                        source_observed_at=observed_at,
                        source_hash=record.record_id,
                        verification_status="verified" if is_verified else "provisional",
                        confidence=1.0 if is_verified else 0.85,
                    )
                )

    plan_payload = {
        "historical_company_creates": historical_company_creates,
        "current_company_creates": current_company_creates,
        "current_ticker_fills": current_ticker_fills,
        "security_creates": security_creates,
        "identity_creates": identity_creates,
        "membership_creates": membership_creates,
        "verified_memberships": verified_memberships,
        "provisional_memberships": provisional_memberships,
        "source_interval_count": len(records),
        "exact_independent_interval_count": len(verified_intervals),
    }
    plan = MaterializationPlan(**plan_payload, plan_hash=_hash(plan_payload))
    if apply:
        session.commit()
    else:
        session.rollback()
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize HU-2 production universe rows.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--component-history", required=True, type=Path)
    parser.add_argument("--component-history-ref", required=True)
    parser.add_argument("--current-components", required=True, type=Path)
    parser.add_argument("--ticker-lineages", required=True, type=Path)
    parser.add_argument("--ticker-lineages-ref", required=True)
    parser.add_argument("--observed-at")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    observed_at = (
        datetime.fromisoformat(args.observed_at.replace("Z", "+00:00"))
        if args.observed_at
        else datetime.now(UTC)
    )
    if observed_at.tzinfo is None:
        raise ValueError("observed-at must be timezone-aware")
    records = HistoricalComponentHistoryAdapter(
        source_ref=args.component_history_ref
    ).load(args.component_history)
    current = _load_current(args.current_components)
    verified = _verified_interval_keys(args.ticker_lineages, args.ticker_lineages_ref)

    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            plan = materialize(
                session,
                records=records,
                current_by_cik=current,
                verified_intervals=verified,
                observed_at=observed_at,
                apply=args.apply,
            )
    finally:
        engine.dispose()

    payload = plan.as_dict()
    payload["applied"] = bool(args.apply)
    payload["interpretation"] = (
        "Historical-only issuers use ticker=null. Membership is verified only on exact interval "
        "agreement between the pinned lawcal and fja05680 sources; other source-backed intervals "
        "remain provisional. No fuzzy identity matching is used."
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
