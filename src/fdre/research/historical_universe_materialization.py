"""Conservative interval materialization for Historical Universe membership events."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from fdre.research.historical_universe import UniverseMembershipRecord
from fdre.research.historical_universe_evidence import ReconciledMembershipEvent

MaterializationIssueCode = Literal[
    "orphan_removal",
    "duplicate_addition",
    "conflicting_events",
    "open_membership_unbounded",
]
_MATERIALIZATION_SCHEMA_VERSION = "fdre-hu-membership-materialization-v1"


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class MembershipMaterializationIssue:
    code: MaterializationIssueCode
    universe_code: str
    security_id: int
    effective_at: date
    event_hashes: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class MembershipMaterializationResult:
    memberships: tuple[UniverseMembershipRecord, ...]
    issues: tuple[MembershipMaterializationIssue, ...]
    materialization_id: str


def _membership_source_hash(
    addition: ReconciledMembershipEvent,
    removal: ReconciledMembershipEvent,
) -> str:
    return _hash(
        {
            "schema_version": _MATERIALIZATION_SCHEMA_VERSION,
            "universe_code": addition.universe_code,
            "security_id": addition.security_id,
            "effective_from": addition.effective_at.isoformat(),
            "effective_to": removal.effective_at.isoformat(),
            "addition_hash": addition.reconciliation_hash,
            "removal_hash": removal.reconciliation_hash,
        }
    )


def materialize_membership_intervals(
    events: Sequence[ReconciledMembershipEvent],
) -> MembershipMaterializationResult:
    """Build only intervals whose start and end are both supported by evidence.

    HU-2 intentionally does not infer a start before the first observed removal or an end after
    the last observed addition. Those cases remain explicit audit issues until another source or
    anchor snapshot bounds the interval.
    """

    grouped: dict[tuple[str, int], list[ReconciledMembershipEvent]] = defaultdict(list)
    for event in events:
        grouped[(event.universe_code.strip().lower(), event.security_id)].append(event)

    memberships: list[UniverseMembershipRecord] = []
    issues: list[MembershipMaterializationIssue] = []

    for (universe_code, security_id), security_events in sorted(grouped.items()):
        by_date: dict[date, list[ReconciledMembershipEvent]] = defaultdict(list)
        for event in security_events:
            by_date[event.effective_at].append(event)

        open_addition: ReconciledMembershipEvent | None = None
        for effective_at in sorted(by_date):
            dated_events = sorted(
                by_date[effective_at],
                key=lambda item: (item.event_type, item.reconciliation_hash),
            )
            event_types = {event.event_type for event in dated_events}
            direct_conflict = len(event_types) > 1 or any(
                "opposite_event_same_date" in event.conflict_codes for event in dated_events
            )
            if direct_conflict:
                issues.append(
                    MembershipMaterializationIssue(
                        code="conflicting_events",
                        universe_code=universe_code,
                        security_id=security_id,
                        effective_at=effective_at,
                        event_hashes=tuple(
                            sorted(event.reconciliation_hash for event in dated_events)
                        ),
                        detail="addition/removal conflict on the same effective date",
                    )
                )
                continue

            event = dated_events[0]
            if event.event_type == "addition":
                if open_addition is not None:
                    issues.append(
                        MembershipMaterializationIssue(
                            code="duplicate_addition",
                            universe_code=universe_code,
                            security_id=security_id,
                            effective_at=effective_at,
                            event_hashes=(
                                open_addition.reconciliation_hash,
                                event.reconciliation_hash,
                            ),
                            detail="new addition observed before the prior addition was removed",
                        )
                    )
                    continue
                open_addition = event
                continue

            if open_addition is None:
                issues.append(
                    MembershipMaterializationIssue(
                        code="orphan_removal",
                        universe_code=universe_code,
                        security_id=security_id,
                        effective_at=effective_at,
                        event_hashes=(event.reconciliation_hash,),
                        detail="removal has no evidence-bounded membership start",
                    )
                )
                continue

            status = (
                "verified"
                if open_addition.verification_status == "verified"
                and event.verification_status == "verified"
                else "provisional"
            )
            confidence = min(open_addition.confidence, event.confidence)
            memberships.append(
                UniverseMembershipRecord(
                    universe_code=universe_code,
                    security_id=security_id,
                    effective_from=open_addition.effective_at,
                    effective_to=event.effective_at,
                    source_hash=_membership_source_hash(open_addition, event),
                    verification_status=status,
                    confidence=confidence,
                )
            )
            open_addition = None

        if open_addition is not None:
            issues.append(
                MembershipMaterializationIssue(
                    code="open_membership_unbounded",
                    universe_code=universe_code,
                    security_id=security_id,
                    effective_at=open_addition.effective_at,
                    event_hashes=(open_addition.reconciliation_hash,),
                    detail=(
                        "addition has no observed removal/end anchor; interval is not materialized"
                    ),
                )
            )

    memberships.sort(
        key=lambda item: (item.universe_code, item.security_id, item.effective_from)
    )
    issues.sort(
        key=lambda item: (item.universe_code, item.security_id, item.effective_at, item.code)
    )
    payload = {
        "schema_version": _MATERIALIZATION_SCHEMA_VERSION,
        "memberships": [
            {
                "universe_code": item.universe_code,
                "security_id": item.security_id,
                "effective_from": item.effective_from.isoformat(),
                "effective_to": item.effective_to.isoformat() if item.effective_to else None,
                "source_hash": item.source_hash,
                "verification_status": item.verification_status,
                "confidence": item.confidence,
            }
            for item in memberships
        ],
        "issues": [
            {
                "code": item.code,
                "universe_code": item.universe_code,
                "security_id": item.security_id,
                "effective_at": item.effective_at.isoformat(),
                "event_hashes": list(item.event_hashes),
            }
            for item in issues
        ],
    }
    return MembershipMaterializationResult(
        memberships=tuple(memberships),
        issues=tuple(issues),
        materialization_id=_hash(payload),
    )
