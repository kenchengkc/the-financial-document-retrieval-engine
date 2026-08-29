"""End-to-end Historical Universe v1 / HU-2 reconstruction and audit."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from fdre.research.historical_universe import SecurityIdentityRecord, UniverseMembershipRecord
from fdre.research.historical_universe_evidence import (
    HistoricalUniverseEvidenceAudit,
    IdentityResolution,
    MembershipEvidence,
    ReconciledMembershipEvent,
    reconcile_membership_evidence,
)
from fdre.research.historical_universe_identity import (
    IssuerNameResolution,
    SecCikNameIndex,
    StableSecurityRecord,
    resolve_membership_with_sec_issuer_fallback,
)
from fdre.research.historical_universe_materialization import (
    MembershipMaterializationIssue,
    materialize_membership_intervals,
)

_PIPELINE_SCHEMA_VERSION = "fdre-hu2-reconstruction-audit-v1"


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class HistoricalUniverseDataAudit:
    universe_code: str
    evidence_count: int
    source_count: int
    coverage_start: date | None
    coverage_end: date | None
    issuer_resolution_counts: tuple[tuple[str, int], ...]
    security_resolution_counts: tuple[tuple[str, int], ...]
    security_resolution_method_counts: tuple[tuple[str, int], ...]
    verified_event_count: int
    provisional_event_count: int
    conflict_event_count: int
    materialized_interval_count: int
    verified_interval_count: int
    provisional_interval_count: int
    materialization_issue_counts: tuple[tuple[str, int], ...]
    audit_id: str


@dataclass(frozen=True, slots=True)
class HistoricalUniverseReconstructionResult:
    resolutions: tuple[IdentityResolution, ...]
    issuer_resolutions: tuple[IssuerNameResolution | None, ...]
    events: tuple[ReconciledMembershipEvent, ...]
    memberships: tuple[UniverseMembershipRecord, ...]
    materialization_issues: tuple[MembershipMaterializationIssue, ...]
    evidence_audit: HistoricalUniverseEvidenceAudit
    audit: HistoricalUniverseDataAudit


def _count_pairs(values: Sequence[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(values).items()))


def run_hu2_reconstruction(
    evidence: Sequence[MembershipEvidence],
    *,
    identities: Sequence[SecurityIdentityRecord],
    issuer_index: SecCikNameIndex,
    securities: Sequence[StableSecurityRecord],
) -> HistoricalUniverseReconstructionResult:
    """Resolve, reconcile, materialize, and audit one HU-2 evidence batch."""

    ordered_evidence = tuple(sorted(evidence, key=lambda item: item.evidence_id))
    resolutions: list[IdentityResolution] = []
    issuer_resolutions: list[IssuerNameResolution | None] = []
    for record in ordered_evidence:
        resolution, issuer_resolution = resolve_membership_with_sec_issuer_fallback(
            record,
            identities=identities,
            issuer_index=issuer_index,
            securities=securities,
        )
        resolutions.append(resolution)
        issuer_resolutions.append(issuer_resolution)

    reconciliation = reconcile_membership_evidence(ordered_evidence, resolutions)
    materialization = materialize_membership_intervals(reconciliation.events)

    issuer_statuses = [
        resolution.status if resolution is not None else "not_attempted"
        for resolution in issuer_resolutions
    ]
    security_statuses = [resolution.status for resolution in resolutions]
    resolution_methods = [resolution.method for resolution in resolutions]
    materialization_codes = [issue.code for issue in materialization.issues]
    source_names = sorted({record.source for record in ordered_evidence})
    dates = sorted(record.effective_at for record in ordered_evidence)
    verified_intervals = sum(
        membership.verification_status == "verified"
        for membership in materialization.memberships
    )
    provisional_intervals = sum(
        membership.verification_status == "provisional"
        for membership in materialization.memberships
    )

    audit_payload = {
        "schema_version": _PIPELINE_SCHEMA_VERSION,
        "universe_code": reconciliation.audit.universe_code,
        "evidence_ids": [record.evidence_id for record in ordered_evidence],
        "issuer_resolution_hashes": sorted(
            resolution.resolution_hash
            for resolution in issuer_resolutions
            if resolution is not None
        ),
        "security_resolutions": [
            {
                "evidence_id": resolution.evidence_id,
                "status": resolution.status,
                "method": resolution.method,
                "security_id": resolution.security_id,
                "cik": resolution.cik,
                "candidate_security_ids": list(resolution.candidate_security_ids),
            }
            for resolution in resolutions
        ],
        "reconciliation_audit_id": reconciliation.audit.audit_id,
        "materialization_id": materialization.materialization_id,
    }
    audit = HistoricalUniverseDataAudit(
        universe_code=reconciliation.audit.universe_code,
        evidence_count=len(ordered_evidence),
        source_count=len(source_names),
        coverage_start=dates[0] if dates else None,
        coverage_end=dates[-1] if dates else None,
        issuer_resolution_counts=_count_pairs(issuer_statuses),
        security_resolution_counts=_count_pairs(security_statuses),
        security_resolution_method_counts=_count_pairs(resolution_methods),
        verified_event_count=reconciliation.audit.verified_event_count,
        provisional_event_count=reconciliation.audit.provisional_event_count,
        conflict_event_count=reconciliation.audit.conflict_event_count,
        materialized_interval_count=len(materialization.memberships),
        verified_interval_count=verified_intervals,
        provisional_interval_count=provisional_intervals,
        materialization_issue_counts=_count_pairs(materialization_codes),
        audit_id=_hash(audit_payload),
    )
    return HistoricalUniverseReconstructionResult(
        resolutions=tuple(resolutions),
        issuer_resolutions=tuple(issuer_resolutions),
        events=reconciliation.events,
        memberships=materialization.memberships,
        materialization_issues=materialization.issues,
        evidence_audit=reconciliation.audit,
        audit=audit,
    )
