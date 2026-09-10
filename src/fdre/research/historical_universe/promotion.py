"""Materialize source-backed HU-2 issuer, security, identity, and membership rows.

The materializer is deliberately conservative:
- historical-only issuers use ticker=NULL rather than a synthetic current ticker;
- the SEC-filed starting snapshot is materialized from 500 point-in-time CIK/symbol identities;
- later exact CIK + normalized-symbol claims never rewrite that starting identity;
- ticker identity is asserted only across periods where that exact CIK/symbol is observed as an
  S&P constituent (plus the removal boundary day needed to identify the departing security);
- lawcal ``created_at`` is the fallback symbol-validity boundary; an exact independent addition
  observation may establish the earlier historical ticker, but terminal symbols cannot cross the
  identity-safe starting snapshot;
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
    canonical_component_cik,
)
from fdre.research.historical_universe_boundary import (
    BOUNDARY_ADJUDICATION_SCHEMA_VERSION,
)
from fdre.research.historical_universe_identity import normalize_cik
from fdre.research.historical_universe_lineage import TickerMembershipLineageAdapter
from fdre.universe import universe_from_session

_SCHEMA_VERSION = "fdre-hu2-production-materialization-v4"
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
class AnchorConstituentExpectation:
    cik: str
    symbol: str
    name: str
    membership_effective_to: date | None
    source_hash: str

    @property
    def key(self) -> tuple[str, str]:
        return self.cik, self.symbol


@dataclass(frozen=True, slots=True)
class AnchorExpectation:
    anchor_id: str
    universe_code: str
    effective_at: date
    constituents: tuple[AnchorConstituentExpectation, ...]

    @property
    def constituent_count(self) -> int:
        return len(self.constituents)

    @property
    def display_symbols(self) -> tuple[str, ...]:
        return tuple(sorted(item.symbol for item in self.constituents))


@dataclass(frozen=True, slots=True)
class BoundaryVerification:
    audit_id: str
    verified_record_ids: frozenset[str]
    membership_verified_record_ids: frozenset[str] = frozenset()
    identity_verified_record_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class MaterializationPlan:
    anchor_security_count: int
    historical_company_creates: int
    current_company_creates: int
    current_ticker_fills: int
    security_creates: int
    identity_creates: int
    membership_creates: int
    verified_memberships: int
    provisional_memberships: int
    source_validity_adjusted_memberships: int
    cross_source_boundary_verified_memberships: int
    source_interval_count: int
    exact_independent_interval_count: int
    plan_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "anchor_security_count": self.anchor_security_count,
            "historical_company_creates": self.historical_company_creates,
            "current_company_creates": self.current_company_creates,
            "current_ticker_fills": self.current_ticker_fills,
            "security_creates": self.security_creates,
            "identity_creates": self.identity_creates,
            "membership_creates": self.membership_creates,
            "verified_memberships": self.verified_memberships,
            "provisional_memberships": self.provisional_memberships,
            "source_validity_adjusted_memberships": (
                self.source_validity_adjusted_memberships
            ),
            "cross_source_boundary_verified_memberships": (
                self.cross_source_boundary_verified_memberships
            ),
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
            symbol = (row["symbol"] or "").strip().upper()
            cik = canonical_component_cik(symbol, row["cik"] or "")
            issuer = CurrentIssuer(
                symbol=symbol,
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
    verified_record_ids: frozenset[str] = frozenset(),
) -> bool:
    exact_interval_verified = (
        not record.added_approximate
        and not record.removed_approximate
        and (_symbol(record.symbol), record.effective_from, record.effective_to)
        in verified_intervals
    )
    return exact_interval_verified or record.record_id in verified_record_ids


def _identity_claims(
    records: Sequence[HistoricalComponentRecord],
    verified_record_ids: frozenset[str] = frozenset(),
) -> tuple[IdentityClaim, ...]:
    """Build only source-observed identity spans, preserving gaps between index tenures."""

    claims: list[IdentityClaim] = []
    starts = {
        record.record_id: (
            record.effective_from
            if record.record_id in verified_record_ids
            else record.source_valid_from
        )
        for record in records
    }
    for record in sorted(records, key=lambda item: (starts[item.record_id], item.record_id)):
        identity_start = starts[record.record_id]
        # The removal boundary is itself evidence about the departing security. Extending one day
        # makes that date queryable without claiming the identity beyond the boundary.
        claim_end = record.effective_to + timedelta(days=1) if record.effective_to else None
        if not claims:
            claims.append(IdentityClaim(identity_start, claim_end, (record,)))
            continue
        previous = claims[-1]
        if previous.effective_to is not None and identity_start > previous.effective_to:
            claims.append(IdentityClaim(identity_start, claim_end, (record,)))
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
    raw_anchor = payload.get("identity_safe_anchor", payload)
    if not isinstance(raw_anchor, dict):
        raise ValueError("materialization anchor lacks identity_safe_anchor")
    raw_constituents = raw_anchor.get("constituents")
    if not isinstance(raw_constituents, list):
        raise ValueError("materialization anchor constituents must be a list")
    constituents: list[AnchorConstituentExpectation] = []
    for row in raw_constituents:
        if not isinstance(row, dict):
            raise ValueError("materialization anchor constituent must be an object")
        cik = normalize_cik(str(row.get("cik", "")))
        symbol = _symbol(str(row.get("symbol", "")))
        name = str(row.get("name", "")).strip()
        source_hash = str(row.get("source_hash", "")).strip()
        if not symbol or not name or len(source_hash) != 64:
            raise ValueError("materialization anchor constituent identity is incomplete")
        raw_end = row.get("membership_effective_to")
        effective_to = date.fromisoformat(str(raw_end)) if raw_end else None
        constituents.append(
            AnchorConstituentExpectation(
                cik=cik,
                symbol=symbol,
                name=name,
                membership_effective_to=effective_to,
                source_hash=source_hash,
            )
        )
    raw_count = raw_anchor.get("constituent_count")
    if isinstance(raw_count, bool) or not isinstance(raw_count, int):
        raise ValueError("materialization anchor constituent_count must be an integer")
    if raw_count != len(constituents):
        raise ValueError("materialization anchor constituent_count is inconsistent")
    if raw_count != 500:
        raise ValueError("materialization requires exactly 500 identity-safe securities")
    keys = [item.key for item in constituents]
    if len(set(keys)) != len(keys):
        raise ValueError("materialization anchor contains duplicate security identities")
    anchor_id = str(raw_anchor.get("anchor_id", "")).strip()
    universe_code = str(raw_anchor.get("universe_code", "sp500")).strip().lower()
    if not anchor_id:
        raise ValueError("materialization anchor anchor_id is required")
    canonical_anchor = {key: value for key, value in raw_anchor.items() if key != "anchor_id"}
    if anchor_id != _hash(canonical_anchor):
        raise ValueError("materialization anchor_id does not match its constituents")
    if not universe_code:
        raise ValueError("materialization anchor universe_code is required")
    return AnchorExpectation(
        anchor_id=anchor_id,
        universe_code=universe_code,
        effective_at=date.fromisoformat(str(raw_anchor["effective_at"])),
        constituents=tuple(sorted(constituents, key=lambda item: item.key)),
    )


def _load_boundary_verification(path: Path) -> BoundaryVerification:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("boundary audit must be a JSON object")
    audit_id = str(payload.get("audit_id", "")).strip()
    if len(audit_id) != 64:
        raise ValueError("boundary audit audit_id must be a SHA-256 digest")
    raw_intervals = payload.get("intervals")
    if not isinstance(raw_intervals, list):
        raise ValueError("boundary audit intervals must be a list")
    expected_audit_id = _hash(
        {
            "schema_version": BOUNDARY_ADJUDICATION_SCHEMA_VERSION,
            "intervals": raw_intervals,
        }
    )
    if audit_id != expected_audit_id:
        raise ValueError("boundary audit audit_id does not match its interval decisions")
    verified_ids: set[str] = set()
    membership_verified_ids: set[str] = set()
    identity_verified_ids: set[str] = set()
    for raw_interval in raw_intervals:
        if not isinstance(raw_interval, dict):
            raise ValueError("boundary audit interval must be an object")
        record_id = str(raw_interval.get("record_id", "")).strip()
        if len(record_id) != 64:
            raise ValueError("boundary audit record_id must be a SHA-256 digest")
        membership_verified = (
            raw_interval.get("membership_boundaries_verified") is True
        )
        identity_verified = raw_interval.get("point_in_time_symbol_valid") is True
        if membership_verified:
            membership_verified_ids.add(record_id)
        if identity_verified:
            identity_verified_ids.add(record_id)
        if raw_interval.get("status") == "verified":
            if not membership_verified or not identity_verified:
                raise ValueError("verified boundary row is not point-in-time materializable")
            verified_ids.add(record_id)
    return BoundaryVerification(
        audit_id=audit_id,
        verified_record_ids=frozenset(verified_ids),
        membership_verified_record_ids=frozenset(membership_verified_ids),
        identity_verified_record_ids=frozenset(identity_verified_ids),
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
    expected = Counter(f"{item.cik}/{item.symbol}" for item in anchor.constituents)
    provisional_count: int | None = None
    strict_count: int | None = None
    provisional_id: str | None = None
    replay_id: str | None = None
    strict_id: str | None = None
    missing: tuple[str, ...] = tuple(sorted(expected.elements()))
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
            f"{normalize_cik(row.cik)}/{_symbol(row.symbol)}"
            for row in provisional.constituents
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
        strict_securities = Counter(
            f"{normalize_cik(row.cik)}/{_symbol(row.symbol)}"
            for row in strict.constituents
        )
        if strict_securities != expected:
            strict_error = "strict snapshot securities do not match the identity-safe anchor"
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
    boundary_verification: BoundaryVerification | None = None,
    anchor: AnchorExpectation | None = None,
) -> MaterializationPlan:
    companies = list(session.scalars(select(Company).order_by(Company.id)))
    companies_by_cik = {company.cik: company for company in companies}
    companies_by_id = {company.id: company for company in companies}
    companies_by_ticker = {
        _symbol(company.ticker): company for company in companies if company.ticker
    }
    existing_security_by_key = _existing_security_by_key(session, companies_by_id)

    anchor_by_key = {item.key: item for item in anchor.constituents} if anchor else {}
    anchor_keys = set(anchor_by_key)
    grouped: dict[tuple[str, str], list[HistoricalComponentRecord]] = defaultdict(list)
    latest_by_cik: dict[str, HistoricalComponentRecord] = {}
    for record in records:
        if anchor is not None:
            active_at_anchor = record.source_valid_from <= anchor.effective_at and (
                record.effective_to is None or anchor.effective_at < record.effective_to
            )
            anchor_exact_backfill = (
                _component_key(record) in anchor_keys
                and (
                    record.effective_from <= anchor.effective_at
                    or record.effective_to
                    == anchor_by_key[_component_key(record)].membership_effective_to
                )
            )
            if active_at_anchor or anchor_exact_backfill:
                # The independently reconciled starting snapshot owns this part of the interval.
                # Later terminalized rows must not be projected back across it.
                continue
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
    source_validity_adjusted_memberships = 0
    cross_source_boundary_verified_memberships = 0
    anchor_security_count = len(anchor.constituents) if anchor else 0

    # Create/fill issuer rows first so every Security continues to reference the canonical issuer
    # table while current-company APIs can exclude ticker=NULL rows.
    anchor_by_cik = {item.cik: item for item in anchor.constituents} if anchor else {}
    all_ciks = sorted({record.cik for record in records} | set(anchor_by_cik))
    for cik in all_ciks:
        company = companies_by_cik.get(cik)
        current = current_by_cik.get(cik)
        latest = latest_by_cik.get(cik)
        anchor_item = anchor_by_cik.get(cik)
        if company is None:
            ticker_owner = (
                companies_by_ticker.get(_symbol(current.symbol))
                if current is not None
                else None
            )
            if ticker_owner is not None and current is not None:
                raise ValueError(
                    f"current ticker {current.symbol} maps to source CIK {cik} but already "
                    f"belongs to production CIK {ticker_owner.cik}"
                )
            if current is not None:
                current_company_creates += 1
            else:
                historical_company_creates += 1
            if stage:
                company = Company(
                    ticker=current.symbol if current is not None else None,
                    cik=cik,
                    name=(
                        current.name
                        if current is not None
                        else latest.name
                        if latest is not None
                        else anchor_item.name
                        if anchor_item is not None
                        else cik
                    ),
                    sector=(
                        current.sector
                        if current is not None
                        else latest.sector
                        if latest is not None
                        else None
                    ),
                )
                session.add(company)
                session.flush()
                companies_by_cik[cik] = company
                companies_by_id[company.id] = company
                if company.ticker:
                    companies_by_ticker[_symbol(company.ticker)] = company
        elif current is not None and company.ticker is None:
            current_ticker_fills += 1
            ticker_owner = companies_by_ticker.get(_symbol(current.symbol))
            if ticker_owner is not None and ticker_owner.id != company.id:
                raise ValueError(
                    f"current ticker {current.symbol} already belongs to another company"
                )
            if stage:
                company.ticker = current.symbol
                companies_by_ticker[_symbol(current.symbol)] = company

    # Stage the independently reconciled starting snapshot before applying later component rows.
    # Every row is verified by the complete SEC-filed holdings schedule plus its dated identity
    # decision.  End dates merely delimit when later (possibly provisional) evidence takes over.
    if anchor is not None:
        for item in anchor.constituents:
            company = companies_by_cik.get(item.cik)
            security = existing_security_by_key.get(item.key)
            if security is None:
                security_creates += 1
                if stage:
                    if company is None:
                        raise RuntimeError(f"anchor issuer {item.cik} was not materialized")
                    security = Security(company_id=company.id, security_type="common_stock")
                    session.add(security)
                    session.flush()
                    existing_security_by_key[item.key] = security
            if security is None:
                identity_creates += 1
                membership_creates += 1
                verified_memberships += 1
                continue

            existing_identities = list(
                session.scalars(
                    select(SecurityIdentityPeriod)
                    .where(SecurityIdentityPeriod.security_id == security.id)
                    .order_by(SecurityIdentityPeriod.effective_from)
                )
            )
            identity_end = item.membership_effective_to
            future_starts = [
                identity.effective_from
                for identity in existing_identities
                if anchor.effective_at < identity.effective_from
                and (identity_end is None or identity.effective_from < identity_end)
            ]
            if future_starts:
                boundary = min(future_starts)
                identity_end = min(identity_end, boundary) if identity_end else boundary
            identity_exists = any(
                identity.symbol in {item.symbol, item.symbol.replace("-", ".")}
                and identity.effective_from <= anchor.effective_at
                and _interval_end_after(identity.effective_to, anchor.effective_at)
                for identity in existing_identities
            )
            if not identity_exists:
                identity_creates += 1
                if stage:
                    session.add(
                        SecurityIdentityPeriod(
                            security_id=security.id,
                            symbol=item.symbol,
                            name=item.name,
                            exchange=None,
                            effective_from=anchor.effective_at,
                            effective_to=identity_end,
                            source="sec-edgar-ishares-ivv-nq+identity-adjudication",
                            source_url=None,
                            source_observed_at=observed_at,
                            source_hash=item.source_hash,
                            verification_status="verified",
                            confidence=1.0,
                        )
                    )
            existing_membership = session.scalar(
                select(UniverseMembership).where(
                    UniverseMembership.universe_code == anchor.universe_code,
                    UniverseMembership.security_id == security.id,
                    UniverseMembership.effective_from == anchor.effective_at,
                )
            )
            if existing_membership is None:
                membership_creates += 1
                verified_memberships += 1
                if stage:
                    session.add(
                        UniverseMembership(
                            universe_code=anchor.universe_code,
                            security_id=security.id,
                            effective_from=anchor.effective_at,
                            effective_to=item.membership_effective_to,
                            source="sec-edgar-ishares-ivv-nq+identity-adjudication",
                            source_url=None,
                            source_observed_at=observed_at,
                            source_hash=item.source_hash,
                            verification_status="verified",
                            confidence=1.0,
                        )
                    )
            elif existing_membership.effective_to != item.membership_effective_to:
                raise ValueError(
                    f"anchor membership boundary mismatch for {item.cik}/{item.symbol}"
                )

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
        identity_verified_ids = (
            (
                boundary_verification.identity_verified_record_ids
                or boundary_verification.verified_record_ids
            )
            if boundary_verification is not None
            else frozenset()
        )
        exact_identity_ids = frozenset(
            record.record_id
            for record in source_records
            if not record.added_approximate
            and not record.removed_approximate
            and (_symbol(record.symbol), record.effective_from, record.effective_to)
            in verified_intervals
        )
        supported_identity_ids = identity_verified_ids | exact_identity_ids
        if anchor is not None and key not in anchor_keys:
            supported_identity_ids = frozenset(
                record_id
                for record_id in supported_identity_ids
                if not any(
                    record.record_id == record_id
                    and record.effective_from <= anchor.effective_at
                    for record in source_records
                )
            )
        for claim in _identity_claims(source_records, supported_identity_ids):
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
                        verification_status=(
                            "verified"
                            if all(
                                record.record_id in supported_identity_ids
                                for record in claim.records
                            )
                            else "provisional"
                        ),
                        confidence=(
                            0.98
                            if all(
                                record.record_id in supported_identity_ids
                                for record in claim.records
                            )
                            else 0.85
                        ),
                    )
                    session.add(identity)
                    existing_identities.append(identity)

        for record in source_records:
            identity_supported = record.record_id in supported_identity_ids
            membership_start = (
                record.effective_from if identity_supported else record.source_valid_from
            )
            if membership_start != record.effective_from:
                source_validity_adjusted_memberships += 1
            boundary_verified = (
                boundary_verification is not None
                and record.record_id
                in (
                    boundary_verification.membership_verified_record_ids
                    or boundary_verification.verified_record_ids
                )
            )
            is_verified = _membership_verified(
                record,
                verified_intervals,
                (
                    (
                        boundary_verification.membership_verified_record_ids
                        or boundary_verification.verified_record_ids
                    )
                    if boundary_verification is not None
                    else frozenset()
                ),
            )
            if is_verified:
                verified_memberships += 1
            else:
                provisional_memberships += 1
            if boundary_verified:
                cross_source_boundary_verified_memberships += 1
            if security is None:
                membership_creates += 1
                continue
            existing_membership = session.scalar(
                select(UniverseMembership).where(
                    UniverseMembership.universe_code == "sp500",
                    UniverseMembership.security_id == security.id,
                    UniverseMembership.effective_from == membership_start,
                )
            )
            if existing_membership is not None:
                if existing_membership.effective_to != record.effective_to:
                    raise ValueError(
                        f"membership boundary mismatch for {cik}/{symbol} "
                        f"at {membership_start}"
                    )
                continue
            membership_creates += 1
            if stage:
                source = _SOURCE
                if boundary_verified:
                    source += "+cross-source-boundary-adjudication"
                elif is_verified:
                    source += "+fja05680/sp500-ticker-start-end"
                source_hash = record.record_id
                if boundary_verified:
                    if boundary_verification is None:
                        raise RuntimeError("boundary verification unexpectedly missing")
                    source_hash = _hash(
                        {
                            "record_id": record.record_id,
                            "boundary_audit_id": boundary_verification.audit_id,
                        }
                    )
                session.add(
                    UniverseMembership(
                        universe_code="sp500",
                        security_id=security.id,
                        effective_from=membership_start,
                        effective_to=record.effective_to,
                        source=source,
                        source_url=record.source_ref,
                        source_observed_at=observed_at,
                        source_hash=source_hash,
                        verification_status="verified" if is_verified else "provisional",
                        confidence=1.0 if is_verified else 0.85,
                    )
                )

    plan_payload = {
        "anchor_security_count": anchor_security_count,
        "historical_company_creates": historical_company_creates,
        "current_company_creates": current_company_creates,
        "current_ticker_fills": current_ticker_fills,
        "security_creates": security_creates,
        "identity_creates": identity_creates,
        "membership_creates": membership_creates,
        "verified_memberships": verified_memberships,
        "provisional_memberships": provisional_memberships,
        "source_validity_adjusted_memberships": source_validity_adjusted_memberships,
        "cross_source_boundary_verified_memberships": (
            cross_source_boundary_verified_memberships
        ),
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
    parser.add_argument("--boundary-audit", required=True, type=Path)
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
    boundary_verification = _load_boundary_verification(args.boundary_audit)

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
                    boundary_verification=boundary_verification,
                    anchor=anchor,
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
        "agreement or the pinned cross-source boundary adjudication; other source-backed "
        "intervals remain provisional. lawcal created_at is used only when no independent exact "
        "ticker-start evidence exists. Dry-run planning performs no writes. An explicit apply is "
        "committed only when its strict and provisional anchor snapshots, interval audit, identity "
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
