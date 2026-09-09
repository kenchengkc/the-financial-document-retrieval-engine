"""Identity-aware strict coverage for the historical universe.

A calendar segment is strict-eligible only when every active non-rejected membership is verified
and each verified membership's stable security has exactly one active non-rejected identity whose
status is verified. A provisional competing identity is ambiguity, not a fallback candidate.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from typing import Literal

IDENTITY_STRICT_COVERAGE_SCHEMA_VERSION = "fdre-hu5-identity-strict-coverage-v1"
IssueReason = Literal[
    "membership_not_verified",
    "identity_missing",
    "identity_not_verified",
    "identity_ambiguous",
]


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class IdentityCoverageIdentity:
    identity_id: int
    symbol: str
    effective_from: date
    effective_to: date | None
    verification_status: str
    source_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "identity_id": self.identity_id,
            "symbol": self.symbol,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "verification_status": self.verification_status,
            "source_hash": self.source_hash,
        }


@dataclass(frozen=True, slots=True)
class IdentityCoverageMembership:
    membership_id: int
    security_id: int
    cik: str
    effective_from: date
    effective_to: date | None
    verification_status: str
    source_hash: str
    identities: tuple[IdentityCoverageIdentity, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "membership_id": self.membership_id,
            "security_id": self.security_id,
            "cik": self.cik,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "verification_status": self.verification_status,
            "source_hash": self.source_hash,
            "identities": [item.as_dict() for item in self.identities],
        }


@dataclass(frozen=True, slots=True)
class IdentityCoverageIssue:
    membership_id: int
    security_id: int
    effective_from: date
    effective_to: date
    reason: IssueReason
    active_identity_ids: tuple[int, ...]
    active_symbols: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "membership_id": self.membership_id,
            "security_id": self.security_id,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat(),
            "reason": self.reason,
            "active_identity_ids": list(self.active_identity_ids),
            "active_symbols": list(self.active_symbols),
        }


@dataclass(frozen=True, slots=True)
class IdentityCoverageSegment:
    effective_from: date
    effective_to: date
    day_count: int
    blocker_membership_ids: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat(),
            "day_count": self.day_count,
            "blocker_membership_ids": list(self.blocker_membership_ids),
        }


@dataclass(frozen=True, slots=True)
class IdentityStrictCoverageAudit:
    universe_code: str
    window_start: date
    window_end: date
    day_count: int
    blocked_day_count: int
    strict_eligible_day_count: int
    active_membership_count: int
    provisional_membership_count: int
    relevant_provisional_identity_ids: tuple[int, ...]
    audit_id: str
    issues: tuple[IdentityCoverageIssue, ...]
    segments: tuple[IdentityCoverageSegment, ...]
    blocked_days_by_reason: tuple[tuple[str, int], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": IDENTITY_STRICT_COVERAGE_SCHEMA_VERSION,
            "audit_id": self.audit_id,
            "universe_code": self.universe_code,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "day_count": self.day_count,
            "blocked_day_count": self.blocked_day_count,
            "strict_eligible_day_count": self.strict_eligible_day_count,
            "active_membership_count": self.active_membership_count,
            "provisional_membership_count": self.provisional_membership_count,
            "relevant_provisional_identity_count": len(self.relevant_provisional_identity_ids),
            "relevant_provisional_identity_ids": list(self.relevant_provisional_identity_ids),
            "issues": [item.as_dict() for item in self.issues],
            "segments": [item.as_dict() for item in self.segments],
            "blocked_days_by_reason": [
                {"reason": reason, "day_count": count}
                for reason, count in self.blocked_days_by_reason
            ],
        }


def _bounded_end(value: date | None, *, fallback: date) -> date:
    return value if value is not None else fallback


def _active_identity(identity: IdentityCoverageIdentity, when: date) -> bool:
    return identity.effective_from <= when and (
        identity.effective_to is None or when < identity.effective_to
    )


def _issue_reason(
    membership: IdentityCoverageMembership,
    active_identities: Sequence[IdentityCoverageIdentity],
) -> IssueReason | None:
    if membership.verification_status != "verified":
        return "membership_not_verified"
    if not active_identities:
        return "identity_missing"
    if len(active_identities) > 1:
        return "identity_ambiguous"
    if active_identities[0].verification_status != "verified":
        return "identity_not_verified"
    return None


def _membership_issues(
    membership: IdentityCoverageMembership,
    *,
    window_start: date,
    window_end_exclusive: date,
) -> tuple[IdentityCoverageIssue, ...]:
    start = max(membership.effective_from, window_start)
    end = min(
        _bounded_end(membership.effective_to, fallback=window_end_exclusive),
        window_end_exclusive,
    )
    if end <= start:
        return ()

    boundaries = {start, end}
    for identity in membership.identities:
        identity_start = max(identity.effective_from, start)
        identity_end = min(_bounded_end(identity.effective_to, fallback=end), end)
        if identity_end > identity_start:
            boundaries.update((identity_start, identity_end))

    issues: list[IdentityCoverageIssue] = []
    for segment_start, segment_end in pairwise(sorted(boundaries)):
        active = tuple(
            sorted(
                (
                    identity
                    for identity in membership.identities
                    if _active_identity(identity, segment_start)
                ),
                key=lambda identity: identity.identity_id,
            )
        )
        reason = _issue_reason(membership, active)
        if reason is None:
            continue
        issues.append(
            IdentityCoverageIssue(
                membership_id=membership.membership_id,
                security_id=membership.security_id,
                effective_from=segment_start,
                effective_to=segment_end,
                reason=reason,
                active_identity_ids=tuple(identity.identity_id for identity in active),
                active_symbols=tuple(identity.symbol for identity in active),
            )
        )
    return tuple(issues)


def _overlaps_membership(
    identity: IdentityCoverageIdentity,
    membership: IdentityCoverageMembership,
    *,
    window_start: date,
    window_end_exclusive: date,
) -> bool:
    membership_start = max(membership.effective_from, window_start)
    membership_end = min(
        _bounded_end(membership.effective_to, fallback=window_end_exclusive),
        window_end_exclusive,
    )
    identity_start = max(identity.effective_from, window_start)
    identity_end = min(
        _bounded_end(identity.effective_to, fallback=window_end_exclusive),
        window_end_exclusive,
    )
    return max(membership_start, identity_start) < min(membership_end, identity_end)


def build_identity_strict_coverage_audit(
    memberships: Sequence[IdentityCoverageMembership],
    *,
    universe_code: str,
    window_start: date,
    window_end: date,
) -> IdentityStrictCoverageAudit:
    """Build a deterministic membership+identity completeness audit."""
    if window_end < window_start:
        raise ValueError("window_end must be on or after window_start")
    normalized = universe_code.strip().lower()
    if not normalized:
        raise ValueError("universe_code is required")
    membership_ids = [item.membership_id for item in memberships]
    if len(set(membership_ids)) != len(membership_ids):
        raise ValueError("membership IDs must be unique")

    window_end_exclusive = window_end + timedelta(days=1)
    ordered_memberships = tuple(sorted(memberships, key=lambda item: item.membership_id))
    issues = tuple(
        sorted(
            (
                issue
                for membership in ordered_memberships
                for issue in _membership_issues(
                    membership,
                    window_start=window_start,
                    window_end_exclusive=window_end_exclusive,
                )
            ),
            key=lambda issue: (
                issue.effective_from,
                issue.effective_to,
                issue.membership_id,
                issue.reason,
            ),
        )
    )

    boundaries = {window_start, window_end_exclusive}
    for issue in issues:
        boundaries.update((issue.effective_from, issue.effective_to))
    segments: list[IdentityCoverageSegment] = []
    reason_days: Counter[str] = Counter()
    for segment_start, segment_end in pairwise(sorted(boundaries)):
        active_issues = tuple(
            issue
            for issue in issues
            if issue.effective_from <= segment_start < issue.effective_to
        )
        blocker_ids = tuple(sorted({issue.membership_id for issue in active_issues}))
        segment_day_count = (segment_end - segment_start).days
        segments.append(
            IdentityCoverageSegment(
                effective_from=segment_start,
                effective_to=segment_end,
                day_count=segment_day_count,
                blocker_membership_ids=blocker_ids,
            )
        )
        for reason in {issue.reason for issue in active_issues}:
            reason_days[reason] += segment_day_count

    blocked_days = sum(segment.day_count for segment in segments if segment.blocker_membership_ids)
    day_count = (window_end - window_start).days + 1
    relevant_provisional = tuple(
        sorted(
            {
                identity.identity_id
                for membership in ordered_memberships
                for identity in membership.identities
                if identity.verification_status == "provisional"
                and _overlaps_membership(
                    identity,
                    membership,
                    window_start=window_start,
                    window_end_exclusive=window_end_exclusive,
                )
            }
        )
    )
    provisional_memberships = sum(
        membership.verification_status == "provisional"
        for membership in ordered_memberships
    )
    payload = {
        "schema_version": IDENTITY_STRICT_COVERAGE_SCHEMA_VERSION,
        "universe_code": normalized,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "memberships": [membership.as_dict() for membership in ordered_memberships],
        "issues": [issue.as_dict() for issue in issues],
        "segments": [segment.as_dict() for segment in segments],
    }
    return IdentityStrictCoverageAudit(
        universe_code=normalized,
        window_start=window_start,
        window_end=window_end,
        day_count=day_count,
        blocked_day_count=blocked_days,
        strict_eligible_day_count=day_count - blocked_days,
        active_membership_count=len(ordered_memberships),
        provisional_membership_count=provisional_memberships,
        relevant_provisional_identity_ids=relevant_provisional,
        audit_id=_hash(payload),
        issues=issues,
        segments=tuple(segments),
        blocked_days_by_reason=tuple(sorted(reason_days.items())),
    )
