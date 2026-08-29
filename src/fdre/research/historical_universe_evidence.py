"""Historical Universe v1 source-evidence normalization and reconciliation.

HU-2 keeps raw constituent-change observations separate from materialized universe
membership. Source evidence is immutable and provenance-addressed; identity resolution
and cross-source reconciliation are derived decisions that can be rerun as the security
master improves.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models.historical_universe import UniverseMembershipEvidence
from fdre.research.historical_universe import SecurityIdentityRecord

MembershipEventType = Literal["addition", "removal"]
EffectiveSession = Literal["before_open", "after_close", "unspecified"]
ResolutionStatus = Literal["resolved", "ambiguous", "unresolved"]
ResolutionMethod = Literal[
    "cik_symbol_exact",
    "cik_exact",
    "symbol_exact",
    "symbol_name_exact",
    "unresolved",
]
ReconciliationStatus = Literal["verified", "provisional"]

_EVIDENCE_SCHEMA_VERSION = "fdre-hu-membership-evidence-v1"
_RECONCILIATION_SCHEMA_VERSION = "fdre-hu-membership-reconciliation-v1"
_AUDIT_SCHEMA_VERSION = "fdre-hu-membership-audit-v1"
_EVENT_TYPES = frozenset({"addition", "removal"})
_EFFECTIVE_SESSIONS = frozenset({"before_open", "after_close", "unspecified"})


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _active(identity: SecurityIdentityRecord, when: date) -> bool:
    return identity.effective_from <= when and (
        identity.effective_to is None or when < identity.effective_to
    )


def _normalize_symbol(value: str) -> str:
    return value.strip().upper().replace(".", "-")


def _normalize_cik(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    stripped = value.strip()
    if not stripped.isdigit():
        return stripped
    return stripped.zfill(10)


def _normalize_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())
    return normalized or None


def canonical_source_record_hash(record: Mapping[str, object]) -> str:
    """Hash one raw source record without depending on input mapping order."""

    canonical = {str(key): "" if value is None else str(value) for key, value in record.items()}
    return _sha256_json(canonical)


@dataclass(frozen=True, slots=True)
class MembershipEvidence:
    """One immutable normalized observation from a constituent-change source."""

    universe_code: str
    event_type: MembershipEventType
    effective_at: date
    raw_symbol: str
    source: str
    source_observed_at: datetime
    source_record_hash: str
    announced_at: date | None = None
    effective_session: EffectiveSession = "unspecified"
    raw_name: str | None = None
    raw_cik: str | None = None
    source_url: str | None = None
    source_record_id: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.universe_code.strip():
            raise ValueError("universe_code is required")
        if self.event_type not in _EVENT_TYPES:
            raise ValueError(f"unsupported event_type: {self.event_type}")
        if not self.raw_symbol.strip():
            raise ValueError("raw_symbol is required")
        if not self.source.strip():
            raise ValueError("source is required")
        if not _aware(self.source_observed_at):
            raise ValueError("source_observed_at must be timezone-aware")
        if len(self.source_record_hash) != 64:
            raise ValueError("source_record_hash must be a SHA-256 hex digest")
        if self.effective_session not in _EFFECTIVE_SESSIONS:
            raise ValueError(f"unsupported effective_session: {self.effective_session}")

    @property
    def evidence_id(self) -> str:
        """Deterministic normalized evidence identity."""

        payload = {
            "schema_version": _EVIDENCE_SCHEMA_VERSION,
            "universe_code": self.universe_code.strip().lower(),
            "event_type": self.event_type,
            "effective_at": self.effective_at.isoformat(),
            "announced_at": self.announced_at.isoformat() if self.announced_at else None,
            "effective_session": self.effective_session,
            "raw_symbol": self.raw_symbol.strip(),
            "raw_name": self.raw_name,
            "raw_cik": self.raw_cik,
            "source": self.source.strip(),
            "source_url": self.source_url,
            "source_record_id": self.source_record_id,
            "source_observed_at": self.source_observed_at.isoformat(),
            "source_record_hash": self.source_record_hash,
            "metadata": list(self.metadata),
        }
        return _sha256_json(payload)


class MembershipEvidenceAdapter(Protocol):
    """Provider-neutral local-file adapter contract."""

    source_name: str

    def load(self, path: Path, *, observed_at: datetime) -> tuple[MembershipEvidence, ...]: ...


class SnpHistoryCsvAdapter:
    """Normalize the public ``shawnlinxl/snp-history`` CSV format.

    The adapter intentionally accepts a local file. FDRE does not download, bundle, or
    redistribute the upstream dataset, and it does not promote its observations to verified
    membership merely because they parse successfully.
    """

    source_name = "shawnlinxl/snp-history"
    default_source_url = (
        "https://github.com/shawnlinxl/snp-history/blob/master/data/history.csv"
    )

    def __init__(self, *, universe_code: str = "sp500", source_url: str | None = None) -> None:
        self.universe_code = universe_code
        self.source_url = source_url or self.default_source_url

    @staticmethod
    def _parse_date(value: str, field_name: str, row_number: int) -> date:
        try:
            return datetime.strptime(value.strip(), "%m/%d/%Y").date()
        except ValueError as exc:
            raise ValueError(
                f"invalid {field_name} date on row {row_number}: {value!r}"
            ) from exc

    @staticmethod
    def _session(value: str | None) -> EffectiveSession:
        normalized = (value or "").strip().lower().replace("-", " ")
        if normalized in {"after close", "after market close"}:
            return "after_close"
        if normalized in {"before open", "before market open"}:
            return "before_open"
        return "unspecified"

    def load(self, path: Path, *, observed_at: datetime) -> tuple[MembershipEvidence, ...]:
        if not _aware(observed_at):
            raise ValueError("observed_at must be timezone-aware")

        evidence: list[MembershipEvidence] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {
                "Announced",
                "Implemented",
                "Addition",
                "Addition Ticker",
                "Removal",
                "Removal Ticker",
            }
            if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
                missing = sorted(required - set(reader.fieldnames or ()))
                raise ValueError(f"missing required snp-history columns: {missing}")

            for row_number, row in enumerate(reader, start=2):
                implemented = self._parse_date(row["Implemented"], "Implemented", row_number)
                announced_raw = (row.get("Announced") or "").strip()
                announced = (
                    self._parse_date(announced_raw, "Announced", row_number)
                    if announced_raw
                    else None
                )
                session = self._session(row.get(""))
                record_hash = canonical_source_record_hash(row)
                row_id = str(row_number - 1)

                removal_type = (row.get("Removal Type") or "").strip()
                removal_reason = (row.get("Reason for Removal") or "").strip()

                for event_type, name_key, symbol_key in (
                    ("addition", "Addition", "Addition Ticker"),
                    ("removal", "Removal", "Removal Ticker"),
                ):
                    raw_symbol = (row.get(symbol_key) or "").strip()
                    raw_name = (row.get(name_key) or "").strip()
                    if not raw_symbol and not raw_name:
                        continue
                    if not raw_symbol:
                        raise ValueError(
                            f"missing {symbol_key} on row {row_number} with a named constituent"
                        )
                    metadata: list[tuple[str, str]] = []
                    if event_type == "removal" and removal_type:
                        metadata.append(("removal_type", removal_type))
                    if event_type == "removal" and removal_reason:
                        metadata.append(("removal_reason", removal_reason))

                    evidence.append(
                        MembershipEvidence(
                            universe_code=self.universe_code,
                            event_type=event_type,  # type: ignore[arg-type]
                            effective_at=implemented,
                            announced_at=announced,
                            effective_session=session,
                            raw_symbol=raw_symbol,
                            raw_name=raw_name or None,
                            source=self.source_name,
                            source_url=self.source_url,
                            source_observed_at=observed_at,
                            source_record_id=row_id,
                            source_record_hash=record_hash,
                            metadata=tuple(metadata),
                        )
                    )

        return tuple(evidence)


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    """Derived mapping from one evidence record to the stable security master."""

    evidence_id: str
    status: ResolutionStatus
    method: ResolutionMethod
    confidence: float
    security_id: int | None = None
    cik: str | None = None
    candidate_security_ids: tuple[int, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("resolution confidence must be between 0 and 1")
        if self.status == "resolved":
            if self.security_id is None or self.security_id <= 0 or not self.cik:
                raise ValueError("resolved identity requires security_id and cik")
        elif self.security_id is not None or self.cik is not None:
            raise ValueError("non-resolved identity cannot carry a resolved security")


def _candidate_security_ids(records: Sequence[SecurityIdentityRecord]) -> tuple[int, ...]:
    return tuple(sorted({record.security_id for record in records}))


def _resolved_identity(
    evidence: MembershipEvidence,
    records: Sequence[SecurityIdentityRecord],
    *,
    method: ResolutionMethod,
    confidence: float,
) -> IdentityResolution:
    security_ids = _candidate_security_ids(records)
    if len(security_ids) != 1:
        return IdentityResolution(
            evidence_id=evidence.evidence_id,
            status="ambiguous",
            method=method,
            confidence=0.0,
            candidate_security_ids=security_ids,
            reason="multiple stable securities match the evidence",
        )
    matching = next(record for record in records if record.security_id == security_ids[0])
    return IdentityResolution(
        evidence_id=evidence.evidence_id,
        status="resolved",
        method=method,
        confidence=confidence,
        security_id=matching.security_id,
        cik=matching.cik,
        candidate_security_ids=security_ids,
    )


def resolve_membership_evidence(
    evidence: MembershipEvidence,
    identities: Sequence[SecurityIdentityRecord],
) -> IdentityResolution:
    """Conservatively resolve historical source evidence to one stable security.

    No fuzzy ticker or future-identity inference is used. CIK and symbol conflicts fail into an
    ambiguous state rather than silently preferring one identifier.
    """

    active = [
        identity
        for identity in identities
        if identity.verification_status != "rejected" and _active(identity, evidence.effective_at)
    ]
    raw_symbol = _normalize_symbol(evidence.raw_symbol)
    raw_cik = _normalize_cik(evidence.raw_cik)
    symbol_matches = [
        identity for identity in active if _normalize_symbol(identity.symbol) == raw_symbol
    ]
    cik_matches = [
        identity for identity in active if raw_cik is not None and _normalize_cik(identity.cik) == raw_cik
    ]

    if raw_cik is not None and symbol_matches and cik_matches:
        intersection = [
            identity
            for identity in symbol_matches
            if identity.security_id in {candidate.security_id for candidate in cik_matches}
        ]
        if intersection:
            return _resolved_identity(
                evidence,
                intersection,
                method="cik_symbol_exact",
                confidence=1.0,
            )
        return IdentityResolution(
            evidence_id=evidence.evidence_id,
            status="ambiguous",
            method="cik_symbol_exact",
            confidence=0.0,
            candidate_security_ids=tuple(
                sorted(set(_candidate_security_ids(symbol_matches) + _candidate_security_ids(cik_matches)))
            ),
            reason="source CIK and historical symbol resolve to different securities",
        )

    if raw_cik is not None and cik_matches:
        return _resolved_identity(evidence, cik_matches, method="cik_exact", confidence=0.99)

    if symbol_matches:
        symbol_security_ids = _candidate_security_ids(symbol_matches)
        if len(symbol_security_ids) == 1:
            return _resolved_identity(
                evidence,
                symbol_matches,
                method="symbol_exact",
                confidence=0.95,
            )

        raw_name = _normalize_name(evidence.raw_name)
        if raw_name is not None:
            name_matches = [
                identity
                for identity in symbol_matches
                if _normalize_name(identity.name) == raw_name
            ]
            if name_matches and len(_candidate_security_ids(name_matches)) == 1:
                return _resolved_identity(
                    evidence,
                    name_matches,
                    method="symbol_name_exact",
                    confidence=0.90,
                )

        return IdentityResolution(
            evidence_id=evidence.evidence_id,
            status="ambiguous",
            method="symbol_exact",
            confidence=0.0,
            candidate_security_ids=symbol_security_ids,
            reason="historical symbol maps to multiple active securities",
        )

    return IdentityResolution(
        evidence_id=evidence.evidence_id,
        status="unresolved",
        method="unresolved",
        confidence=0.0,
        reason="no active CIK/symbol identity matched at the source effective date",
    )


@dataclass(frozen=True, slots=True)
class ReconciledMembershipEvent:
    """Cross-source membership event after identity resolution."""

    universe_code: str
    event_type: MembershipEventType
    security_id: int
    cik: str
    effective_at: date
    announced_at: date | None
    effective_session: EffectiveSession
    evidence_ids: tuple[str, ...]
    distinct_sources: int
    verification_status: ReconciliationStatus
    confidence: float
    conflict_codes: tuple[str, ...]
    reconciliation_hash: str


@dataclass(frozen=True, slots=True)
class HistoricalUniverseEvidenceAudit:
    """Deterministic coverage and reconciliation diagnostics for an HU-2 batch."""

    universe_code: str
    evidence_count: int
    source_count: int
    resolved_count: int
    ambiguous_count: int
    unresolved_count: int
    reconciled_event_count: int
    verified_event_count: int
    provisional_event_count: int
    conflict_event_count: int
    additions: int
    removals: int
    coverage_start: date | None
    coverage_end: date | None
    per_source_counts: tuple[tuple[str, int], ...]
    ambiguous_evidence_ids: tuple[str, ...]
    unresolved_evidence_ids: tuple[str, ...]
    audit_id: str


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    events: tuple[ReconciledMembershipEvent, ...]
    audit: HistoricalUniverseEvidenceAudit


def _event_hash(
    *,
    universe_code: str,
    event_type: MembershipEventType,
    security_id: int,
    effective_at: date,
    evidence_ids: Sequence[str],
    conflict_codes: Sequence[str],
) -> str:
    return _sha256_json(
        {
            "schema_version": _RECONCILIATION_SCHEMA_VERSION,
            "universe_code": universe_code,
            "event_type": event_type,
            "security_id": security_id,
            "effective_at": effective_at.isoformat(),
            "evidence_ids": sorted(evidence_ids),
            "conflict_codes": sorted(conflict_codes),
        }
    )


def reconcile_membership_evidence(
    evidence: Sequence[MembershipEvidence],
    resolutions: Sequence[IdentityResolution],
    *,
    min_distinct_sources_for_verified: int = 2,
) -> ReconciliationResult:
    """Reconcile resolved observations without manufacturing certainty.

    One-source events remain provisional. Two or more distinct sources can produce a verified
    event only when there is no direct opposite-event conflict for the same security/date.
    Session-timing disagreement is retained as a conflict diagnostic but does not change the
    membership effective date itself.
    """

    if min_distinct_sources_for_verified < 2:
        raise ValueError("verified reconciliation requires at least two distinct sources")

    evidence_by_id = {record.evidence_id: record for record in evidence}
    if len(evidence_by_id) != len(evidence):
        raise ValueError("duplicate evidence_id in reconciliation input")
    resolution_by_id = {resolution.evidence_id: resolution for resolution in resolutions}
    if set(resolution_by_id) != set(evidence_by_id):
        raise ValueError("resolutions must cover every evidence record exactly once")

    grouped: dict[
        tuple[str, int, str, date], list[tuple[MembershipEvidence, IdentityResolution]]
    ] = defaultdict(list)
    event_types_by_security_date: dict[tuple[str, int, date], set[str]] = defaultdict(set)

    for evidence_id, record in evidence_by_id.items():
        resolution = resolution_by_id[evidence_id]
        if resolution.status != "resolved" or resolution.security_id is None or resolution.cik is None:
            continue
        key = (
            record.universe_code.strip().lower(),
            resolution.security_id,
            record.event_type,
            record.effective_at,
        )
        grouped[key].append((record, resolution))
        event_types_by_security_date[(key[0], key[1], key[3])].add(record.event_type)

    events: list[ReconciledMembershipEvent] = []
    for (universe_code, security_id, event_type_raw, effective_at), items in grouped.items():
        event_type: MembershipEventType = event_type_raw  # type: ignore[assignment]
        evidence_ids = tuple(sorted(record.evidence_id for record, _ in items))
        sources = {record.source.strip() for record, _ in items}
        announced_dates = [record.announced_at for record, _ in items if record.announced_at]
        sessions = {record.effective_session for record, _ in items}
        conflict_codes: list[str] = []
        if len(event_types_by_security_date[(universe_code, security_id, effective_at)]) > 1:
            conflict_codes.append("opposite_event_same_date")
        if len(sessions) > 1:
            conflict_codes.append("effective_session_disagreement")

        direct_conflict = "opposite_event_same_date" in conflict_codes
        verification_status: ReconciliationStatus = (
            "verified"
            if len(sources) >= min_distinct_sources_for_verified and not direct_conflict
            else "provisional"
        )
        average_confidence = sum(resolution.confidence for _, resolution in items) / len(items)
        source_factor = 1.0 if len(sources) >= min_distinct_sources_for_verified else 0.8
        conflict_factor = 0.5 if direct_conflict else 1.0
        confidence = round(min(1.0, average_confidence * source_factor * conflict_factor), 6)
        effective_session: EffectiveSession = (
            next(iter(sessions)) if len(sessions) == 1 else "unspecified"
        )
        cik = items[0][1].cik
        assert cik is not None
        reconciliation_hash = _event_hash(
            universe_code=universe_code,
            event_type=event_type,
            security_id=security_id,
            effective_at=effective_at,
            evidence_ids=evidence_ids,
            conflict_codes=conflict_codes,
        )
        events.append(
            ReconciledMembershipEvent(
                universe_code=universe_code,
                event_type=event_type,
                security_id=security_id,
                cik=cik,
                effective_at=effective_at,
                announced_at=min(announced_dates) if announced_dates else None,
                effective_session=effective_session,
                evidence_ids=evidence_ids,
                distinct_sources=len(sources),
                verification_status=verification_status,
                confidence=confidence,
                conflict_codes=tuple(sorted(conflict_codes)),
                reconciliation_hash=reconciliation_hash,
            )
        )

    events.sort(
        key=lambda item: (
            item.effective_at,
            item.security_id,
            item.event_type,
            item.reconciliation_hash,
        )
    )

    audit = build_evidence_audit(evidence, resolutions, events)
    return ReconciliationResult(events=tuple(events), audit=audit)


def build_evidence_audit(
    evidence: Sequence[MembershipEvidence],
    resolutions: Sequence[IdentityResolution],
    events: Sequence[ReconciledMembershipEvent],
) -> HistoricalUniverseEvidenceAudit:
    """Build a stable HU-2 coverage/reconciliation report."""

    evidence_by_id = {record.evidence_id: record for record in evidence}
    resolution_by_id = {resolution.evidence_id: resolution for resolution in resolutions}
    if set(evidence_by_id) != set(resolution_by_id):
        raise ValueError("audit requires one resolution for every evidence record")

    source_counts: dict[str, int] = defaultdict(int)
    for record in evidence:
        source_counts[record.source.strip()] += 1

    ambiguous_ids = tuple(
        sorted(
            resolution.evidence_id
            for resolution in resolutions
            if resolution.status == "ambiguous"
        )
    )
    unresolved_ids = tuple(
        sorted(
            resolution.evidence_id
            for resolution in resolutions
            if resolution.status == "unresolved"
        )
    )
    dates = sorted(record.effective_at for record in evidence)
    universe_codes = {record.universe_code.strip().lower() for record in evidence}
    universe_code = next(iter(universe_codes)) if len(universe_codes) == 1 else "mixed"
    event_payload = [
        {
            "hash": event.reconciliation_hash,
            "status": event.verification_status,
            "conflicts": list(event.conflict_codes),
        }
        for event in events
    ]
    audit_payload = {
        "schema_version": _AUDIT_SCHEMA_VERSION,
        "universe_code": universe_code,
        "evidence_ids": sorted(evidence_by_id),
        "resolutions": [
            {
                "evidence_id": resolution.evidence_id,
                "status": resolution.status,
                "method": resolution.method,
                "security_id": resolution.security_id,
                "confidence": resolution.confidence,
            }
            for resolution in sorted(resolutions, key=lambda item: item.evidence_id)
        ],
        "events": event_payload,
    }

    return HistoricalUniverseEvidenceAudit(
        universe_code=universe_code,
        evidence_count=len(evidence),
        source_count=len(source_counts),
        resolved_count=sum(resolution.status == "resolved" for resolution in resolutions),
        ambiguous_count=len(ambiguous_ids),
        unresolved_count=len(unresolved_ids),
        reconciled_event_count=len(events),
        verified_event_count=sum(event.verification_status == "verified" for event in events),
        provisional_event_count=sum(
            event.verification_status == "provisional" for event in events
        ),
        conflict_event_count=sum(bool(event.conflict_codes) for event in events),
        additions=sum(event.event_type == "addition" for event in events),
        removals=sum(event.event_type == "removal" for event in events),
        coverage_start=dates[0] if dates else None,
        coverage_end=dates[-1] if dates else None,
        per_source_counts=tuple(sorted(source_counts.items())),
        ambiguous_evidence_ids=ambiguous_ids,
        unresolved_evidence_ids=unresolved_ids,
        audit_id=_sha256_json(audit_payload),
    )


def audit_to_dict(audit: HistoricalUniverseEvidenceAudit) -> dict[str, object]:
    return {
        "universe_code": audit.universe_code,
        "evidence_count": audit.evidence_count,
        "source_count": audit.source_count,
        "resolved_count": audit.resolved_count,
        "ambiguous_count": audit.ambiguous_count,
        "unresolved_count": audit.unresolved_count,
        "reconciled_event_count": audit.reconciled_event_count,
        "verified_event_count": audit.verified_event_count,
        "provisional_event_count": audit.provisional_event_count,
        "conflict_event_count": audit.conflict_event_count,
        "additions": audit.additions,
        "removals": audit.removals,
        "coverage_start": audit.coverage_start.isoformat() if audit.coverage_start else None,
        "coverage_end": audit.coverage_end.isoformat() if audit.coverage_end else None,
        "per_source_counts": dict(audit.per_source_counts),
        "ambiguous_evidence_ids": list(audit.ambiguous_evidence_ids),
        "unresolved_evidence_ids": list(audit.unresolved_evidence_ids),
        "audit_id": audit.audit_id,
    }


def persist_membership_evidence(
    session: Session,
    records: Sequence[MembershipEvidence],
) -> int:
    """Idempotently persist immutable normalized evidence; return inserted row count."""

    evidence_ids = [record.evidence_id for record in records]
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError("duplicate evidence_id in persistence batch")
    existing = set(
        session.scalars(
            select(UniverseMembershipEvidence.evidence_id).where(
                UniverseMembershipEvidence.evidence_id.in_(evidence_ids)
            )
        )
    )
    inserted = 0
    for record in records:
        if record.evidence_id in existing:
            continue
        session.add(
            UniverseMembershipEvidence(
                evidence_id=record.evidence_id,
                universe_code=record.universe_code.strip().lower(),
                event_type=record.event_type,
                effective_at=record.effective_at,
                announced_at=record.announced_at,
                effective_session=record.effective_session,
                raw_symbol=record.raw_symbol,
                raw_name=record.raw_name,
                raw_cik=record.raw_cik,
                source=record.source,
                source_url=record.source_url,
                source_record_id=record.source_record_id,
                source_observed_at=record.source_observed_at,
                source_record_hash=record.source_record_hash,
                metadata_json=dict(record.metadata) or None,
            )
        )
        inserted += 1
    session.flush()
    return inserted
