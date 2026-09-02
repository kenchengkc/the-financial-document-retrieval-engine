"""Historical-universe input gate and lineage helpers for HU-5."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.models import Company, Document
from apps.api.app.models.historical_universe import (
    Security,
    SecurityIdentityPeriod,
    UniverseMembership,
)
from fdre.research.event_study import FilingEvent
from fdre.research.historical_universe import (
    SecurityIdentityRecord,
    UniverseMembershipRecord,
    UniverseSnapshot,
    VerificationStatus,
    build_universe_snapshot,
)

HU5_UNIVERSE_GATE_SCHEMA_VERSION = "fdre-hu5-universe-gate-v1"
HU5_EVENT_LINEAGE_SCHEMA_VERSION = "fdre-hu5-event-universe-lineage-v1"


@dataclass(frozen=True, slots=True)
class HU5UniverseRecords:
    memberships: tuple[UniverseMembershipRecord, ...]
    identities: tuple[SecurityIdentityRecord, ...]


@dataclass(frozen=True, slots=True)
class HU5UniverseDateStatus:
    as_of: str
    eligible: bool
    snapshot_id: str | None
    constituent_count: int
    error: str | None


@dataclass(frozen=True, slots=True)
class HU5UniverseGate:
    universe_code: str
    input_provenance_id: str
    window_start: str
    window_end: str
    day_count: int
    strict_eligible_day_count: int
    invalid_day_count: int
    gate_manifest_id: str
    dates: tuple[HU5UniverseDateStatus, ...]


@dataclass(frozen=True, slots=True)
class HU5EventUniverseLineage:
    accession_number: str
    as_of: str
    snapshot_id: str
    security_id: int
    cik: str
    symbol: str
    membership_source_hash: str
    identity_source_hash: str


@dataclass(frozen=True, slots=True)
class HU5ResolvedEvents:
    events: tuple[FilingEvent, ...]
    lineage: tuple[HU5EventUniverseLineage, ...]
    universe_lineage_id: str
    excluded_invalid_date: int
    excluded_not_member: int
    ambiguous_accessions: tuple[str, ...]


def _verification_status(value: str) -> VerificationStatus:
    if value not in {"verified", "provisional", "rejected"}:
        raise ValueError(f"unsupported historical-universe verification status: {value}")
    return cast(VerificationStatus, value)


def load_hu5_universe_records(
    session: Session,
    *,
    universe_code: str,
    window_start: date,
    window_end: date,
) -> HU5UniverseRecords:
    """Load all non-rejected membership/identity records overlapping an inclusive window."""
    if window_end < window_start:
        raise ValueError("window_end must be on or after window_start")
    normalized = universe_code.strip().lower()
    if not normalized:
        raise ValueError("universe_code is required")

    membership_rows = session.execute(
        select(
            UniverseMembership.universe_code,
            UniverseMembership.security_id,
            UniverseMembership.effective_from,
            UniverseMembership.effective_to,
            UniverseMembership.source_hash,
            UniverseMembership.verification_status,
            UniverseMembership.confidence,
        )
        .where(
            UniverseMembership.universe_code == normalized,
            UniverseMembership.effective_from <= window_end,
            (
                UniverseMembership.effective_to.is_(None)
                | (UniverseMembership.effective_to > window_start)
            ),
            UniverseMembership.verification_status != "rejected",
        )
        .order_by(
            UniverseMembership.security_id,
            UniverseMembership.effective_from,
            UniverseMembership.id,
        )
    ).all()
    memberships = tuple(
        UniverseMembershipRecord(
            universe_code=str(row.universe_code),
            security_id=int(row.security_id),
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            source_hash=str(row.source_hash),
            verification_status=_verification_status(str(row.verification_status)),
            confidence=float(row.confidence),
        )
        for row in membership_rows
    )
    security_ids = tuple(sorted({row.security_id for row in memberships}))
    if not security_ids:
        return HU5UniverseRecords(memberships=memberships, identities=())

    identity_rows = session.execute(
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
        .where(
            SecurityIdentityPeriod.security_id.in_(security_ids),
            SecurityIdentityPeriod.effective_from <= window_end,
            (
                SecurityIdentityPeriod.effective_to.is_(None)
                | (SecurityIdentityPeriod.effective_to > window_start)
            ),
            SecurityIdentityPeriod.verification_status != "rejected",
        )
        .order_by(
            SecurityIdentityPeriod.security_id,
            SecurityIdentityPeriod.effective_from,
            SecurityIdentityPeriod.id,
        )
    ).all()
    identities = tuple(
        SecurityIdentityRecord(
            security_id=int(row.security_id),
            cik=str(row.cik),
            symbol=str(row.symbol),
            name=str(row.name) if row.name is not None else None,
            exchange=str(row.exchange) if row.exchange is not None else None,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            source_hash=str(row.source_hash),
            verification_status=_verification_status(str(row.verification_status)),
            confidence=float(row.confidence),
        )
        for row in identity_rows
    )
    return HU5UniverseRecords(memberships=memberships, identities=identities)


def strict_hu5_snapshot(
    records: HU5UniverseRecords,
    *,
    universe_code: str,
    as_of: date,
) -> UniverseSnapshot:
    """Build one strict snapshot; provisional evidence is never opted into."""
    snapshot = build_universe_snapshot(
        universe_code=universe_code,
        as_of=as_of,
        memberships=records.memberships,
        identities=records.identities,
        include_provisional=False,
    )
    if not snapshot.constituents:
        raise ValueError(f"strict universe snapshot is empty as_of={as_of.isoformat()}")
    return snapshot


def hu5_universe_input_provenance_id(records: HU5UniverseRecords) -> str:
    """Fingerprint exact membership and identity evidence loaded for the HU-5 gate."""
    payload = {
        "memberships": [
            {
                "universe_code": item.universe_code,
                "security_id": item.security_id,
                "effective_from": item.effective_from.isoformat(),
                "effective_to": item.effective_to.isoformat() if item.effective_to else None,
                "source_hash": item.source_hash,
                "verification_status": item.verification_status,
                "confidence": format(item.confidence, ".17g"),
            }
            for item in records.memberships
        ],
        "identities": [
            {
                "security_id": item.security_id,
                "cik": item.cik,
                "symbol": item.symbol,
                "effective_from": item.effective_from.isoformat(),
                "effective_to": item.effective_to.isoformat() if item.effective_to else None,
                "source_hash": item.source_hash,
                "verification_status": item.verification_status,
                "confidence": format(item.confidence, ".17g"),
            }
            for item in records.identities
        ],
    }
    return _stable_digest(payload)


def build_hu5_universe_gate(
    records: HU5UniverseRecords,
    *,
    universe_code: str,
    window_start: date,
    window_end: date,
) -> HU5UniverseGate:
    """Measure strict snapshot eligibility for every calendar date in the target window."""
    if window_end < window_start:
        raise ValueError("window_end must be on or after window_start")
    dates: list[HU5UniverseDateStatus] = []
    cursor = window_start
    while cursor <= window_end:
        try:
            snapshot = strict_hu5_snapshot(
                records,
                universe_code=universe_code,
                as_of=cursor,
            )
        except ValueError as exc:
            dates.append(
                HU5UniverseDateStatus(
                    as_of=cursor.isoformat(),
                    eligible=False,
                    snapshot_id=None,
                    constituent_count=0,
                    error=str(exc),
                )
            )
        else:
            dates.append(
                HU5UniverseDateStatus(
                    as_of=cursor.isoformat(),
                    eligible=True,
                    snapshot_id=snapshot.snapshot_id,
                    constituent_count=len(snapshot.constituents),
                    error=None,
                )
            )
        cursor += timedelta(days=1)

    input_provenance_id = hu5_universe_input_provenance_id(records)
    payload = {
        "schema_version": HU5_UNIVERSE_GATE_SCHEMA_VERSION,
        "input_provenance_id": input_provenance_id,
        "universe_code": universe_code.strip().lower(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "dates": [asdict(item) for item in dates],
    }
    manifest_id = _stable_digest(payload)
    eligible = sum(item.eligible for item in dates)
    return HU5UniverseGate(
        universe_code=universe_code.strip().lower(),
        input_provenance_id=input_provenance_id,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        day_count=len(dates),
        strict_eligible_day_count=eligible,
        invalid_day_count=len(dates) - eligible,
        gate_manifest_id=manifest_id,
        dates=tuple(dates),
    )


def write_hu5_universe_gate(path: str | Path, gate: HU5UniverseGate) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": HU5_UNIVERSE_GATE_SCHEMA_VERSION,
        "gate_manifest_id": gate.gate_manifest_id,
        "input_provenance_id": gate.input_provenance_id,
        "universe_code": gate.universe_code,
        "window_start": gate.window_start,
        "window_end": gate.window_end,
        "day_count": gate.day_count,
        "strict_eligible_day_count": gate.strict_eligible_day_count,
        "invalid_day_count": gate.invalid_day_count,
        "dates": [asdict(item) for item in gate.dates],
    }
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return destination


def select_historical_issuer_ciks(
    session: Session,
    *,
    universe_code: str,
    window_start: date,
    window_end: date,
    max_issuers: int,
    min_documents: int,
) -> tuple[list[str], dict[str, str]]:
    """Select issuer CIKs from overlapping historical membership, never current ticker identity."""
    if max_issuers <= 0:
        raise ValueError("max_issuers must be positive")
    if min_documents <= 0:
        raise ValueError("min_documents must be positive")
    document_count = func.count(func.distinct(Document.id)).label("documents")
    rows = session.execute(
        select(Company.cik, Company.sector, document_count)
        .join(Security, Security.company_id == Company.id)
        .join(UniverseMembership, UniverseMembership.security_id == Security.id)
        .join(Document, Document.company_id == Company.id)
        .where(
            UniverseMembership.universe_code == universe_code.strip().lower(),
            UniverseMembership.verification_status != "rejected",
            UniverseMembership.effective_from <= window_end,
            (
                UniverseMembership.effective_to.is_(None)
                | (UniverseMembership.effective_to > window_start)
            ),
            Document.form_type.in_(["10-K", "10-Q"]),
            Document.available_at.is_not(None),
        )
        .group_by(Company.id, Company.cik, Company.sector)
        .having(func.count(func.distinct(Document.id)) >= min_documents)
        .order_by(document_count.desc(), Company.cik)
        .limit(max_issuers)
    ).all()
    ciks = [str(row.cik) for row in rows]
    sectors = {str(row.cik): str(row.sector or "Unknown") for row in rows}
    return ciks, sectors


def resolve_hu5_events(
    events: list[FilingEvent],
    *,
    cik_by_accession: dict[str, str],
    records: HU5UniverseRecords,
    gate: HU5UniverseGate,
) -> HU5ResolvedEvents:
    """Map issuer-level filing events to the one verified historical security active that day."""
    eligible_dates = {
        date.fromisoformat(item.as_of)
        for item in gate.dates
        if item.eligible
    }
    snapshot_cache: dict[date, UniverseSnapshot] = {}
    resolved: list[FilingEvent] = []
    lineage: list[HU5EventUniverseLineage] = []
    excluded_invalid_date = 0
    excluded_not_member = 0
    ambiguous: list[str] = []

    for event in events:
        as_of = event.available_at.date()
        if as_of not in eligible_dates:
            excluded_invalid_date += 1
            continue
        cik = cik_by_accession.get(event.accession_number)
        if cik is None:
            ambiguous.append(event.accession_number)
            continue
        snapshot = snapshot_cache.get(as_of)
        if snapshot is None:
            snapshot = strict_hu5_snapshot(
                records,
                universe_code=gate.universe_code,
                as_of=as_of,
            )
            snapshot_cache[as_of] = snapshot
        matches = [item for item in snapshot.constituents if item.cik == cik]
        if not matches:
            excluded_not_member += 1
            continue
        if len(matches) != 1:
            ambiguous.append(event.accession_number)
            continue
        constituent = matches[0]
        resolved.append(event.model_copy(update={"ticker": constituent.symbol.upper()}))
        lineage.append(
            HU5EventUniverseLineage(
                accession_number=event.accession_number,
                as_of=as_of.isoformat(),
                snapshot_id=snapshot.snapshot_id,
                security_id=constituent.security_id,
                cik=cik,
                symbol=constituent.symbol.upper(),
                membership_source_hash=constituent.membership_source_hash,
                identity_source_hash=constituent.identity_source_hash,
            )
        )

    lineage.sort(key=lambda item: (item.as_of, item.accession_number, item.symbol))
    lineage_payload = {
        "schema_version": HU5_EVENT_LINEAGE_SCHEMA_VERSION,
        "gate_manifest_id": gate.gate_manifest_id,
        "events": [asdict(item) for item in lineage],
    }
    return HU5ResolvedEvents(
        events=tuple(resolved),
        lineage=tuple(lineage),
        universe_lineage_id=_stable_digest(lineage_payload),
        excluded_invalid_date=excluded_invalid_date,
        excluded_not_member=excluded_not_member,
        ambiguous_accessions=tuple(sorted(set(ambiguous))),
    )


def _stable_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
