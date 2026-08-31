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
from collections import Counter, defaultdict
from collections.abc import Sequence
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
from fdre.research.historical_universe_anchor import normalize_display_symbol
from fdre.research.historical_universe_identity import normalize_cik
from fdre.research.historical_universe_lineage import TickerMembershipLineageAdapter
from fdre.universe import universe_from_session

_SCHEMA_VERSION = "fdre-hu2-production-materialization-v2"
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
class IdentityClaim:
    effective_from: date
    effective_to: date | None
    records: tuple[HistoricalComponentRecord, ...]


@dataclass(frozen=True, slots=True)
class AnchorExpectation:
    anchor_id: str
    universe_code: str
    effective_at: date
    display_symbols: tuple[str, ...]

    @property
    def constituent_count(self) -> int:
        return len(self.display_symbols)


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


@dataclass(frozen=True, slots=True)
class MaterializationValidation:
    anchor_id: str
    universe_code: str
    as_of: date
    expected_constituent_count: int
    provisional_constituent_count: int | None
    strict_constituent_count: int | None
    provisional_snapshot_id: str | None
    replay_snapshot_id: str | None
    strict_snapshot_id: str | None
    missing_anchor_symbols: tuple[str, ...]
    unexpected_snapshot_symbols: tuple[str, ...]
    provisional_snapshot_error: str | None
    strict_snapshot_error: str | None
    identity_overlap_count: int
    membership_overlap_count: int
    missing_identity_coverage_count: int

    @property
    def deterministic_replay_match(self) -> bool:
        return (
            self.provisional_snapshot_id is not None
            and self.provisional_snapshot_id == self.replay_snapshot_id
        )

    @property
    def provisional_anchor_match(self) -> bool:
        return (
            self.provisional_snapshot_error is None
            and self.provisional_constituent_count == self.expected_constituent_count
            and not self.missing_anchor_symbols
            and not self.unexpected_snapshot_symbols
        )

    @property
    def strict_anchor_match(self) -> bool:
        return (
            self.strict_snapshot_error is None
            and self.strict_constituent_count == self.expected_constituent_count
        )

    @property
    def commit_eligible(self) -> bool:
        return (
            self.provisional_anchor_match
            and self.strict_anchor_match
            and self.deterministic_replay_match
            and self.identity_overlap_count == 0
            and self.membership_overlap_count == 0
            and self.missing_identity_coverage_count == 0
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "anchor_id": self.anchor_id,
            "universe_code": self.universe_code,
            "as_of": self.as_of.isoformat(),
            "expected_constituent_count": self.expected_constituent_count,
            "provisional_constituent_count": self.provisional_constituent_count,
            "strict_constituent_count": self.strict_constituent_count,
            "provisional_snapshot_id": self.provisional_snapshot_id,
            "replay_snapshot_id": self.replay_snapshot_id,
            "strict_snapshot_id": self.strict_snapshot_id,
            "missing_anchor_symbols": list(self.missing_anchor_symbols),
            "unexpected_snapshot_symbols": list(self.unexpected_snapshot_symbols),
            "provisional_snapshot_error": self.provisional_snapshot_error,
            "strict_snapshot_error": self.strict_snapshot_error,
            "deterministic_replay_match": self.deterministic_replay_match,
            "provisional_anchor_match": self.provisional_anchor_match,
            "strict_anchor_match": self.strict_anchor_match,
            "identity_overlap_count": self.identity_overlap_count,
            "membership_overlap_count": self.membership_overlap_count,
            "missing_identity_coverage_count": self.missing_identity_coverage_count,
            "commit_eligible": self.commit_eligible,
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


def _identity_claims(records: Sequence[HistoricalComponentRecord]) -> tuple[IdentityClaim, ...]:
    """Build only source-observed identity spans, preserving gaps between index tenures."""

    claims: list[IdentityClaim] = []
    for record in sorted(records, key=lambda item: (item.effective_from, item.record_id)):
        # The removal boundary is itself evidence about the departing security. Extending one day
        # makes that date queryable without claiming the identity beyond the boundary.
        claim_end = record.effective_to + timedelta(days=1) if record.effective_to else None
        if not claims:
            claims.append(IdentityClaim(record.effective_from, claim_end, (record,)))
            continue
        previous = claims[-1]
        if previous.effective_to is not None and record.effective_from > previous.effective_to:
            claims.append(IdentityClaim(record.effective_from, claim_end, (record,)))
            continue
        merged_end = (
            None
            if previous.effective_to is None or claim_end is None
            else max(previous.effective_to, claim_end)
        )
        claims[-1] = IdentityClaim(
            previous.effective_from,
            merged_end,
            (*previous.records, record),
        )
    return tuple(claims)


def _source_hash_for_group(records: Sequence[HistoricalComponentRecord]) -> str:
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


def _load_anchor(path: Path) -> AnchorExpectation:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("materialization anchor must be a JSON object")
    if payload.get("complete_target_window_anchor") is not True:
        raise ValueError("materialization requires a complete target-window anchor")
    raw_tokens = payload.get("lineage_tokens")
    if not isinstance(raw_tokens, list) or not all(
        isinstance(token, str) and token.strip() for token in raw_tokens
    ):
        raise ValueError("materialization anchor lineage_tokens must be non-empty strings")
    raw_count = payload.get("constituent_count")
    if isinstance(raw_count, bool) or not isinstance(raw_count, int):
        raise ValueError("materialization anchor constituent_count must be an integer")
    if raw_count != len(raw_tokens):
        raise ValueError("materialization anchor constituent_count is inconsistent")
    if not 490 <= raw_count <= 510:
        raise ValueError("materialization anchor constituent_count is implausible")
    anchor_id = str(payload.get("anchor_id", "")).strip()
    universe_code = str(payload.get("universe_code", "sp500")).strip().lower()
    if not anchor_id:
        raise ValueError("materialization anchor anchor_id is required")
    if not universe_code:
        raise ValueError("materialization anchor universe_code is required")
    return AnchorExpectation(
        anchor_id=anchor_id,
        universe_code=universe_code,
        effective_at=date.fromisoformat(str(payload["effective_at"])),
        display_symbols=tuple(
            sorted(normalize_display_symbol(token) for token in raw_tokens)
        ),
    )


def _interval_end_after(end: date | None, point: date) -> bool:
    return end is None or point < end


def _interval_issue_counts(
    session: Session,
    universe_code: str,
) -> tuple[int, int, int]:
    memberships = list(
        session.scalars(
            select(UniverseMembership)
            .where(
                UniverseMembership.universe_code == universe_code,
                UniverseMembership.verification_status != "rejected",
            )
            .order_by(
                UniverseMembership.universe_code,
                UniverseMembership.security_id,
                UniverseMembership.effective_from,
                UniverseMembership.id,
            )
        )
    )
    security_ids = sorted({membership.security_id for membership in memberships})
    identities = (
        list(
            session.scalars(
                select(SecurityIdentityPeriod)
                .where(
                    SecurityIdentityPeriod.security_id.in_(security_ids),
                    SecurityIdentityPeriod.verification_status != "rejected",
                )
                .order_by(
                    SecurityIdentityPeriod.security_id,
                    SecurityIdentityPeriod.effective_from,
                    SecurityIdentityPeriod.id,
                )
            )
        )
        if security_ids
        else []
    )

    identities_by_security: dict[int, list[SecurityIdentityPeriod]] = defaultdict(list)
    for identity in identities:
        identities_by_security[identity.security_id].append(identity)
    memberships_by_key: dict[tuple[str, int], list[UniverseMembership]] = defaultdict(list)
    for membership in memberships:
        memberships_by_key[(membership.universe_code, membership.security_id)].append(membership)

    identity_overlaps = 0
    for identity_rows in identities_by_security.values():
        furthest_end: date | None = identity_rows[0].effective_to
        for identity_row in identity_rows[1:]:
            if furthest_end is None or identity_row.effective_from < furthest_end:
                identity_overlaps += 1
            if furthest_end is not None:
                if identity_row.effective_to is None:
                    furthest_end = None
                elif identity_row.effective_to > furthest_end:
                    furthest_end = identity_row.effective_to

    membership_overlaps = 0
    for membership_rows in memberships_by_key.values():
        furthest_end = membership_rows[0].effective_to
        for membership_row in membership_rows[1:]:
            if furthest_end is None or membership_row.effective_from < furthest_end:
                membership_overlaps += 1
            if furthest_end is not None:
                if membership_row.effective_to is None:
                    furthest_end = None
                elif membership_row.effective_to > furthest_end:
                    furthest_end = membership_row.effective_to

    missing_identity_coverage = 0
    for membership in memberships:
        cursor: date | None = membership.effective_from
        for identity in identities_by_security.get(membership.security_id, []):
            if cursor is None:
                break
            if identity.effective_from > cursor:
                break
            if not _interval_end_after(identity.effective_to, cursor):
                continue
            cursor = identity.effective_to
            if membership.effective_to is not None and (
                cursor is None or membership.effective_to <= cursor
            ):
                break
        covered = (
            cursor is None
            if membership.effective_to is None
            else cursor is None or membership.effective_to <= cursor
        )
        if not covered:
            missing_identity_coverage += 1
    return identity_overlaps, membership_overlaps, missing_identity_coverage


def _counter_rows(counter: Counter[str]) -> tuple[str, ...]:
    return tuple(
        symbol
        for symbol, count in sorted(counter.items())
        for _ in range(count)
    )


def validate_materialized_state(
    session: Session,
    anchor: AnchorExpectation,
) -> MaterializationValidation:
    """Audit the staged HU state before the caller decides whether to commit it."""

    session.flush()
    expected = Counter(anchor.display_symbols)
    provisional_count: int | None = None
    strict_count: int | None = None
    provisional_id: str | None = None
    replay_id: str | None = None
    strict_id: str | None = None
    missing: tuple[str, ...] = anchor.display_symbols
    unexpected: tuple[str, ...] = ()
    provisional_error: str | None = None
    strict_error: str | None = None

    try:
        provisional = universe_from_session(
            session,
            anchor.universe_code,
            as_of=anchor.effective_at,
            include_provisional=True,
        )
        replay = universe_from_session(
            session,
            anchor.universe_code,
            as_of=anchor.effective_at,
            include_provisional=True,
        )
        provisional_count = len(provisional.constituents)
        provisional_id = provisional.snapshot_id
        replay_id = replay.snapshot_id
        actual = Counter(
            normalize_display_symbol(row.symbol) for row in provisional.constituents
        )
        missing = _counter_rows(expected - actual)
        unexpected = _counter_rows(actual - expected)
    except ValueError as exc:
        provisional_error = str(exc)

    try:
        strict = universe_from_session(
            session,
            anchor.universe_code,
            as_of=anchor.effective_at,
        )
        strict_count = len(strict.constituents)
        strict_id = strict.snapshot_id
        strict_symbols = Counter(
            normalize_display_symbol(row.symbol) for row in strict.constituents
        )
        if strict_symbols != expected:
            strict_error = "strict snapshot symbols do not match the complete anchor"
    except ValueError as exc:
        strict_error = str(exc)

    identity_overlaps, membership_overlaps, missing_identity_coverage = (
        _interval_issue_counts(session, anchor.universe_code)
    )
    return MaterializationValidation(
        anchor_id=anchor.anchor_id,
        universe_code=anchor.universe_code,
        as_of=anchor.effective_at,
        expected_constituent_count=anchor.constituent_count,
        provisional_constituent_count=provisional_count,
        strict_constituent_count=strict_count,
        provisional_snapshot_id=provisional_id,
        replay_snapshot_id=replay_id,
        strict_snapshot_id=strict_id,
        missing_anchor_symbols=missing,
        unexpected_snapshot_symbols=unexpected,
        provisional_snapshot_error=provisional_error,
        strict_snapshot_error=strict_error,
        identity_overlap_count=identity_overlaps,
        membership_overlap_count=membership_overlaps,
        missing_identity_coverage_count=missing_identity_coverage,
    )


def materialize(
    session: Session,
    *,
    records: tuple[HistoricalComponentRecord, ...],
    current_by_cik: dict[str, CurrentIssuer],
    verified_intervals: set[tuple[str, date, date | None]],
    observed_at: datetime,
    stage: bool,
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
            if stage:
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
            if stage:
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
    if stage:
        session.flush()
    for key in sorted(grouped):
        cik, symbol = key
        source_records = sorted(
            grouped[key], key=lambda value: (value.effective_from, value.record_id)
        )
        company = companies_by_cik.get(cik)
        security = existing_security_by_key.get(key)
        if security is None:
            security_creates += 1
            if stage:
                if company is None:
                    raise RuntimeError(f"issuer {cik} was not materialized")
                security = Security(company_id=company.id, security_type="common_stock")
                session.add(security)
                session.flush()
                existing_security_by_key[key] = security

        existing_identities = (
            list(
                session.scalars(
                    select(SecurityIdentityPeriod).where(
                        SecurityIdentityPeriod.security_id == security.id,
                        SecurityIdentityPeriod.symbol.in_([symbol, symbol.replace("-", ".")]),
                    )
                )
            )
            if security is not None
            else []
        )
        for claim in _identity_claims(source_records):
            identity_start = claim.effective_from
            identity_end = claim.effective_to
            identity_exists = any(
                identity.effective_from <= identity_start
                and (
                    identity.effective_to is None
                    or (
                        identity_end is not None
                        and identity_end <= identity.effective_to
                    )
                )
                for identity in existing_identities
            )
            if not identity_exists and existing_identities:
                containing = any(
                    identity.effective_from <= identity_start
                    and _interval_end_after(identity.effective_to, identity_start)
                    for identity in existing_identities
                )
                if containing:
                    identity_exists = True
                else:
                    future_starts = [
                        identity.effective_from
                        for identity in existing_identities
                        if identity_start < identity.effective_from
                        and (identity_end is None or identity.effective_from < identity_end)
                    ]
                    if future_starts:
                        boundary = min(future_starts)
                        identity_end = min(identity_end, boundary) if identity_end else boundary
            if not identity_exists and identity_end != identity_start:
                identity_creates += 1
                if stage:
                    if security is None:
                        raise RuntimeError("security must exist before identity materialization")
                    identity = SecurityIdentityPeriod(
                        security_id=security.id,
                        symbol=symbol,
                        name=claim.records[-1].name,
                        exchange=None,
                        effective_from=identity_start,
                        effective_to=identity_end,
                        source=_SOURCE,
                        source_url=claim.records[-1].source_ref,
                        source_observed_at=observed_at,
                        source_hash=_source_hash_for_group(claim.records),
                        verification_status="verified",
                        confidence=0.98,
                    )
                    session.add(identity)
                    existing_identities.append(identity)

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
            if stage:
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
    return MaterializationPlan(**plan_payload, plan_hash=_hash(plan_payload))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize HU-2 production universe rows.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--component-history", required=True, type=Path)
    parser.add_argument("--component-history-ref", required=True)
    parser.add_argument("--current-components", required=True, type=Path)
    parser.add_argument("--ticker-lineages", required=True, type=Path)
    parser.add_argument("--ticker-lineages-ref", required=True)
    parser.add_argument("--anchor", required=True, type=Path)
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
    anchor = _load_anchor(args.anchor)

    engine = create_db_engine(args.database_url)
    try:
        with Session(engine) as session:
            try:
                plan = materialize(
                    session,
                    records=records,
                    current_by_cik=current,
                    verified_intervals=verified,
                    observed_at=observed_at,
                    stage=args.apply,
                )
                if args.apply:
                    validation = validate_materialized_state(session, anchor)
                    validation_payload = validation.as_dict()
                    applied = validation.commit_eligible
                    if applied:
                        session.commit()
                    else:
                        session.rollback()
                else:
                    applied = False
                    validation_payload = {
                        "anchor_id": anchor.anchor_id,
                        "universe_code": anchor.universe_code,
                        "as_of": anchor.effective_at.isoformat(),
                        "status": "not_run",
                        "reason": (
                            "Exact validation requires an explicit staged apply transaction. "
                            "Dry-run planning performs no inserts, updates, or sequence advances."
                        ),
                        "commit_eligible": False,
                    }
                    session.rollback()
            except Exception:
                session.rollback()
                raise
    finally:
        engine.dispose()

    payload = plan.as_dict()
    payload["apply_requested"] = bool(args.apply)
    payload["applied"] = applied
    payload["validation"] = validation_payload
    payload["interpretation"] = (
        "Historical-only issuers use ticker=null. Membership is verified only on exact interval "
        "agreement between the pinned lawcal and fja05680 sources; other source-backed intervals "
        "remain provisional. Dry-run planning performs no writes. An explicit apply is committed "
        "only when its strict and provisional anchor snapshots, interval audit, identity "
        "coverage, and deterministic replay all pass."
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.apply and not applied:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
