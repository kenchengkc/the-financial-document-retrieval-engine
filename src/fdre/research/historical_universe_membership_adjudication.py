"""Fail-closed evidence adjudication for the final HU-5 membership blockers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from fdre.research.historical_universe_lineage import normalize_symbol
from fdre.research.historical_universe_membership_continuity import normalize_cik
from fdre.research.historical_universe_strict_coverage import ProvisionalMembershipBlocker

AdjudicationAction = Literal["verify", "correct_and_verify", "reject"]
EvidenceAuthority = Literal["sp_dji", "sec", "issuer"]
SiblingRole = Literal["predecessor", "successor", "duplicate_cover"]

MEMBERSHIP_ADJUDICATION_SCHEMA_VERSION = "fdre-hu5-membership-adjudication-v1"


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class MembershipAdjudicationEvidence:
    authority: EvidenceAuthority
    source_url: str
    assertion: str

    @property
    def evidence_id(self) -> str:
        return _hash(
            {
                "schema_version": MEMBERSHIP_ADJUDICATION_SCHEMA_VERSION,
                "kind": "authoritative_claim",
                "authority": self.authority,
                "source_url": self.source_url,
                "assertion": self.assertion,
            }
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "authority": self.authority,
            "source_url": self.source_url,
            "assertion": self.assertion,
        }


@dataclass(frozen=True, slots=True)
class IdentityRequirement:
    symbol: str
    effective_from: date
    effective_to: date | None
    verification_status: str
    source_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": normalize_symbol(self.symbol),
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "verification_status": self.verification_status,
            "source_hash": self.source_hash,
        }


@dataclass(frozen=True, slots=True)
class SiblingMembershipRequirement:
    role: SiblingRole
    membership_id: int
    security_id: int
    cik: str
    effective_from: date
    effective_to: date | None
    source_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "membership_id": self.membership_id,
            "security_id": self.security_id,
            "cik": normalize_cik(self.cik),
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "source_hash": self.source_hash,
        }


@dataclass(frozen=True, slots=True)
class LiveSiblingMembership:
    membership_id: int
    security_id: int
    cik: str
    effective_from: date
    effective_to: date | None
    source_hash: str
    verification_status: str


@dataclass(frozen=True, slots=True)
class MembershipAdjudicationCase:
    membership_id: int
    security_id: int
    cik: str
    prior_effective_from: date
    prior_effective_to: date | None
    prior_source_hash: str
    identity: IdentityRequirement
    action: AdjudicationAction
    target_effective_from: date
    target_effective_to: date | None
    evidence: tuple[MembershipAdjudicationEvidence, ...]
    siblings: tuple[SiblingMembershipRequirement, ...]
    reason: str

    def canonical_dict(self) -> dict[str, object]:
        return {
            "membership_id": self.membership_id,
            "security_id": self.security_id,
            "cik": normalize_cik(self.cik),
            "prior_effective_from": self.prior_effective_from.isoformat(),
            "prior_effective_to": (
                self.prior_effective_to.isoformat() if self.prior_effective_to else None
            ),
            "prior_source_hash": self.prior_source_hash,
            "identity": self.identity.as_dict(),
            "action": self.action,
            "target_effective_from": self.target_effective_from.isoformat(),
            "target_effective_to": (
                self.target_effective_to.isoformat() if self.target_effective_to else None
            ),
            "evidence_ids": sorted(item.evidence_id for item in self.evidence),
            "siblings": [
                item.as_dict()
                for item in sorted(self.siblings, key=lambda value: value.membership_id)
            ],
            "reason": self.reason,
        }

    @property
    def decision_hash(self) -> str:
        return _hash(
            {
                "schema_version": MEMBERSHIP_ADJUDICATION_SCHEMA_VERSION,
                **self.canonical_dict(),
            }
        )


@dataclass(frozen=True, slots=True)
class MembershipAdjudicationDecision:
    membership_id: int
    security_id: int
    cik: str
    prior_effective_from: date
    prior_effective_to: date | None
    prior_source_hash: str
    action: AdjudicationAction
    target_effective_from: date
    target_effective_to: date | None
    evidence_ids: tuple[str, ...]
    sibling_membership_ids: tuple[int, ...]
    reason: str
    decision_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "membership_id": self.membership_id,
            "security_id": self.security_id,
            "cik": self.cik,
            "prior_effective_from": self.prior_effective_from.isoformat(),
            "prior_effective_to": (
                self.prior_effective_to.isoformat() if self.prior_effective_to else None
            ),
            "prior_source_hash": self.prior_source_hash,
            "action": self.action,
            "target_effective_from": self.target_effective_from.isoformat(),
            "target_effective_to": (
                self.target_effective_to.isoformat() if self.target_effective_to else None
            ),
            "evidence_ids": list(self.evidence_ids),
            "sibling_membership_ids": list(self.sibling_membership_ids),
            "reason": self.reason,
            "decision_hash": self.decision_hash,
        }


def membership_adjudication_manifest_id(
    cases: Sequence[MembershipAdjudicationCase],
) -> str:
    ordered = sorted(cases, key=lambda item: item.membership_id)
    return _hash(
        {
            "schema_version": MEMBERSHIP_ADJUDICATION_SCHEMA_VERSION,
            "cases": [item.canonical_dict() for item in ordered],
        }
    )


def _validate_case_shape(case: MembershipAdjudicationCase) -> None:
    if not case.evidence:
        raise ValueError(f"membership {case.membership_id} requires authoritative evidence")
    if case.target_effective_to is not None and (
        case.target_effective_to <= case.target_effective_from
    ):
        raise ValueError(f"membership {case.membership_id} has a non-positive target interval")
    prior = (case.prior_effective_from, case.prior_effective_to)
    target = (case.target_effective_from, case.target_effective_to)
    if case.action == "verify" and target != prior:
        raise ValueError(f"verify membership {case.membership_id} cannot change boundaries")
    if case.action == "correct_and_verify" and target == prior:
        raise ValueError(
            f"correct_and_verify membership {case.membership_id} must change a boundary"
        )
    if case.action == "reject" and target != prior:
        raise ValueError(f"reject membership {case.membership_id} cannot change boundaries")


def _matches_identity(
    blocker: ProvisionalMembershipBlocker,
    requirement: IdentityRequirement,
) -> bool:
    expected = requirement.as_dict()
    return any(
        {
            "symbol": normalize_symbol(identity.symbol),
            "effective_from": identity.effective_from.isoformat(),
            "effective_to": (
                identity.effective_to.isoformat() if identity.effective_to else None
            ),
            "verification_status": identity.verification_status,
            "source_hash": identity.source_hash,
        }
        == expected
        for identity in blocker.identities
    )


def _validate_sibling(
    requirement: SiblingMembershipRequirement,
    live: LiveSiblingMembership | None,
) -> None:
    if live is None:
        raise RuntimeError(
            f"required sibling membership {requirement.membership_id} is missing"
        )
    if live.verification_status != "verified":
        raise RuntimeError(
            f"required sibling membership {requirement.membership_id} is not verified"
        )
    expected = requirement.as_dict()
    actual = {
        "role": requirement.role,
        "membership_id": live.membership_id,
        "security_id": live.security_id,
        "cik": normalize_cik(live.cik),
        "effective_from": live.effective_from.isoformat(),
        "effective_to": live.effective_to.isoformat() if live.effective_to else None,
        "source_hash": live.source_hash,
    }
    if actual != expected:
        raise RuntimeError(
            f"required sibling membership {requirement.membership_id} changed"
        )


def plan_membership_adjudication(
    blockers: Sequence[ProvisionalMembershipBlocker],
    *,
    cases: Sequence[MembershipAdjudicationCase],
    live_siblings: Sequence[LiveSiblingMembership],
) -> tuple[MembershipAdjudicationDecision, ...]:
    """Reproduce the reviewed decision for every live blocker, or fail closed."""
    blocker_ids = [item.membership_id for item in blockers]
    case_ids = [item.membership_id for item in cases]
    if len(set(blocker_ids)) != len(blocker_ids):
        raise ValueError("membership blocker IDs must be unique")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("membership adjudication case IDs must be unique")
    if set(blocker_ids) != set(case_ids):
        raise RuntimeError(
            "live provisional membership set differs from the reviewed adjudication manifest"
        )

    blockers_by_id = {item.membership_id: item for item in blockers}
    siblings_by_id = {item.membership_id: item for item in live_siblings}
    if len(siblings_by_id) != len(live_siblings):
        raise ValueError("live sibling membership IDs must be unique")

    decisions: list[MembershipAdjudicationDecision] = []
    for case in sorted(cases, key=lambda item: item.membership_id):
        _validate_case_shape(case)
        blocker = blockers_by_id[case.membership_id]
        if blocker.security_id != case.security_id:
            raise RuntimeError(f"membership {case.membership_id} security changed")
        if normalize_cik(blocker.cik) != normalize_cik(case.cik):
            raise RuntimeError(f"membership {case.membership_id} issuer CIK changed")
        if (
            blocker.effective_from != case.prior_effective_from
            or blocker.effective_to != case.prior_effective_to
        ):
            raise RuntimeError(f"membership {case.membership_id} boundaries changed")
        if blocker.source_hash != case.prior_source_hash:
            raise RuntimeError(f"membership {case.membership_id} source hash changed")
        if not _matches_identity(blocker, case.identity):
            raise RuntimeError(f"membership {case.membership_id} identity anchor changed")
        for sibling in case.siblings:
            _validate_sibling(sibling, siblings_by_id.get(sibling.membership_id))

        evidence_ids = tuple(sorted(item.evidence_id for item in case.evidence))
        sibling_ids = tuple(sorted(item.membership_id for item in case.siblings))
        decisions.append(
            MembershipAdjudicationDecision(
                membership_id=case.membership_id,
                security_id=case.security_id,
                cik=normalize_cik(case.cik),
                prior_effective_from=case.prior_effective_from,
                prior_effective_to=case.prior_effective_to,
                prior_source_hash=case.prior_source_hash,
                action=case.action,
                target_effective_from=case.target_effective_from,
                target_effective_to=case.target_effective_to,
                evidence_ids=evidence_ids,
                sibling_membership_ids=sibling_ids,
                reason=case.reason,
                decision_hash=case.decision_hash,
            )
        )
    return tuple(decisions)


def membership_adjudication_plan_id(
    decisions: Sequence[MembershipAdjudicationDecision],
    *,
    manifest_id: str,
) -> str:
    ordered = sorted(decisions, key=lambda item: item.membership_id)
    return _hash(
        {
            "schema_version": MEMBERSHIP_ADJUDICATION_SCHEMA_VERSION,
            "manifest_id": manifest_id,
            "decisions": [item.as_dict() for item in ordered],
        }
    )
