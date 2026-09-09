"""Deterministic topology records for residual HU-5 identity blockers.

This module intentionally contains no discovery or mutation logic.  It canonicalizes the exact
live identity/membership neighborhood around identity-aware strict-coverage blockers so a later
reviewed adjudication can bind to stable row IDs, intervals, statuses, source hashes, and persisted
SEC evidence instead of reasoning from ticker strings alone.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

RESIDUAL_IDENTITY_TOPOLOGY_SCHEMA_VERSION = "fdre-hu5-residual-identity-topology-v1"


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class IdentityTopologyEvidence:
    evidence_id: str
    cik: str
    symbol: str
    accession_number: str
    filing_date: str
    form_type: str
    concept_name: str
    context_ref: str | None
    source_url: str
    payload_sha256: str
    decision_hash: str
    state_decision_hash: str
    state_lineage_id: str
    projection_plan_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "cik": self.cik,
            "symbol": self.symbol,
            "accession_number": self.accession_number,
            "filing_date": self.filing_date,
            "form_type": self.form_type,
            "concept_name": self.concept_name,
            "context_ref": self.context_ref,
            "source_url": self.source_url,
            "payload_sha256": self.payload_sha256,
            "decision_hash": self.decision_hash,
            "state_decision_hash": self.state_decision_hash,
            "state_lineage_id": self.state_lineage_id,
            "projection_plan_id": self.projection_plan_id,
        }


@dataclass(frozen=True, slots=True)
class IdentityTopologyPeriod:
    identity_id: int
    security_id: int
    symbol: str
    name: str | None
    exchange: str | None
    effective_from: str
    effective_to: str | None
    verification_status: str
    source: str
    source_url: str | None
    source_observed_at: str
    source_hash: str
    confidence: float
    evidence: tuple[IdentityTopologyEvidence, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "identity_id": self.identity_id,
            "security_id": self.security_id,
            "symbol": self.symbol,
            "name": self.name,
            "exchange": self.exchange,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "verification_status": self.verification_status,
            "source": self.source,
            "source_url": self.source_url,
            "source_observed_at": self.source_observed_at,
            "source_hash": self.source_hash,
            "confidence": self.confidence,
            "evidence": [item.as_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class MembershipTopologyPeriod:
    membership_id: int
    universe_code: str
    security_id: int
    effective_from: str
    effective_to: str | None
    verification_status: str
    source: str
    source_url: str | None
    source_observed_at: str
    source_hash: str
    confidence: float

    def as_dict(self) -> dict[str, object]:
        return {
            "membership_id": self.membership_id,
            "universe_code": self.universe_code,
            "security_id": self.security_id,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "verification_status": self.verification_status,
            "source": self.source,
            "source_url": self.source_url,
            "source_observed_at": self.source_observed_at,
            "source_hash": self.source_hash,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class ResidualIdentityTarget:
    identity_id: int
    security_id: int
    cik: str
    symbol: str
    effective_from: str
    effective_to: str | None
    source_hash: str
    issue_membership_ids: tuple[int, ...]
    identity_periods: tuple[IdentityTopologyPeriod, ...]
    memberships: tuple[MembershipTopologyPeriod, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "identity_id": self.identity_id,
            "security_id": self.security_id,
            "cik": self.cik,
            "symbol": self.symbol,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "source_hash": self.source_hash,
            "issue_membership_ids": list(self.issue_membership_ids),
            "identity_periods": [item.as_dict() for item in self.identity_periods],
            "memberships": [item.as_dict() for item in self.memberships],
        }


@dataclass(frozen=True, slots=True)
class ResidualIdentityGap:
    membership_id: int
    security_id: int
    cik: str
    effective_from: str
    effective_to: str
    identity_periods: tuple[IdentityTopologyPeriod, ...]
    memberships: tuple[MembershipTopologyPeriod, ...]

    @property
    def gap_key(self) -> tuple[int, int, str, str]:
        return (
            self.membership_id,
            self.security_id,
            self.effective_from,
            self.effective_to,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "membership_id": self.membership_id,
            "security_id": self.security_id,
            "cik": self.cik,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "identity_periods": [item.as_dict() for item in self.identity_periods],
            "memberships": [item.as_dict() for item in self.memberships],
        }


@dataclass(frozen=True, slots=True)
class ResidualIdentityTopology:
    audit_id: str
    topology_id: str
    targets: tuple[ResidualIdentityTarget, ...]
    gaps: tuple[ResidualIdentityGap, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": RESIDUAL_IDENTITY_TOPOLOGY_SCHEMA_VERSION,
            "audit_id": self.audit_id,
            "topology_id": self.topology_id,
            "target_count": len(self.targets),
            "gap_count": len(self.gaps),
            "targets": [item.as_dict() for item in self.targets],
            "gaps": [item.as_dict() for item in self.gaps],
        }


def _validate_periods(
    *,
    security_id: int,
    identity_periods: tuple[IdentityTopologyPeriod, ...],
    memberships: tuple[MembershipTopologyPeriod, ...],
) -> None:
    identity_ids = [item.identity_id for item in identity_periods]
    if len(identity_ids) != len(set(identity_ids)):
        raise ValueError(f"security {security_id} contains duplicate identity IDs")
    membership_ids = [item.membership_id for item in memberships]
    if len(membership_ids) != len(set(membership_ids)):
        raise ValueError(f"security {security_id} contains duplicate membership IDs")
    if any(item.security_id != security_id for item in identity_periods):
        raise ValueError(f"security {security_id} topology contains a foreign identity period")
    if any(item.security_id != security_id for item in memberships):
        raise ValueError(f"security {security_id} topology contains a foreign membership period")


def build_residual_identity_topology(
    *,
    audit_id: str,
    targets: tuple[ResidualIdentityTarget, ...],
    gaps: tuple[ResidualIdentityGap, ...],
) -> ResidualIdentityTopology:
    """Validate and hash one exact residual identity topology snapshot."""
    if len(audit_id) != 64:
        raise ValueError("audit_id must be a SHA-256 hex digest")

    ordered_targets = tuple(sorted(targets, key=lambda item: item.identity_id))
    target_ids = [item.identity_id for item in ordered_targets]
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("residual target identity IDs must be unique")

    for target in ordered_targets:
        _validate_periods(
            security_id=target.security_id,
            identity_periods=target.identity_periods,
            memberships=target.memberships,
        )
        matching = [
            item
            for item in target.identity_periods
            if item.identity_id == target.identity_id
        ]
        if len(matching) != 1:
            raise ValueError(f"target identity {target.identity_id} is missing from its topology")
        live = matching[0]
        if live.verification_status != "provisional":
            raise ValueError(f"target identity {target.identity_id} is not provisional")
        if (
            live.security_id != target.security_id
            or live.symbol != target.symbol
            or live.effective_from != target.effective_from
            or live.effective_to != target.effective_to
            or live.source_hash != target.source_hash
        ):
            raise ValueError(f"target identity {target.identity_id} live row fields drifted")
        if tuple(sorted(set(target.issue_membership_ids))) != target.issue_membership_ids:
            raise ValueError(
                f"target identity {target.identity_id} issue membership IDs must be sorted unique"
            )
        known_memberships = {item.membership_id for item in target.memberships}
        if not set(target.issue_membership_ids).issubset(known_memberships):
            raise ValueError(
                f"target identity {target.identity_id} references an unknown membership"
            )

    ordered_gaps = tuple(sorted(gaps, key=lambda item: item.gap_key))
    gap_keys = [item.gap_key for item in ordered_gaps]
    if len(gap_keys) != len(set(gap_keys)):
        raise ValueError("residual identity gap keys must be unique")
    for gap in ordered_gaps:
        _validate_periods(
            security_id=gap.security_id,
            identity_periods=gap.identity_periods,
            memberships=gap.memberships,
        )
        if gap.effective_to <= gap.effective_from:
            raise ValueError("residual identity gap must have positive duration")
        if gap.membership_id not in {item.membership_id for item in gap.memberships}:
            raise ValueError(
                f"gap membership {gap.membership_id} is missing from security topology"
            )

    canonical: dict[str, Any] = {
        "schema_version": RESIDUAL_IDENTITY_TOPOLOGY_SCHEMA_VERSION,
        "audit_id": audit_id,
        "targets": [item.as_dict() for item in ordered_targets],
        "gaps": [item.as_dict() for item in ordered_gaps],
    }
    topology_id = _digest(canonical)
    return ResidualIdentityTopology(
        audit_id=audit_id,
        topology_id=topology_id,
        targets=ordered_targets,
        gaps=ordered_gaps,
    )
