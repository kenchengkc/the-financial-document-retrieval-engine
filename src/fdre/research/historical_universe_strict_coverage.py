"""Deterministic coverage audit for provisional historical-universe memberships."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta

STRICT_COVERAGE_SCHEMA_VERSION = "fdre-hu-strict-coverage-v1"


@dataclass(frozen=True, slots=True)
class IdentityContext:
    symbol: str
    effective_from: date
    effective_to: date | None
    verification_status: str
    source_hash: str


@dataclass(frozen=True, slots=True)
class ProvisionalMembershipBlocker:
    membership_id: int
    security_id: int
    cik: str
    effective_from: date
    effective_to: date | None
    source: str
    source_url: str | None
    source_hash: str
    confidence: float
    identities: tuple[IdentityContext, ...] = ()


@dataclass(frozen=True, slots=True)
class StrictCoverageSegment:
    effective_from: date
    effective_to: date
    day_count: int
    blocker_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class GreedyBlockerSelection:
    rank: int
    membership_id: int
    newly_covered_days: int
    remaining_blocked_days: int


@dataclass(frozen=True, slots=True)
class StrictCoverageAudit:
    universe_code: str
    window_start: date
    window_end: date
    day_count: int
    blocked_day_count: int
    strict_eligible_day_count: int
    provisional_membership_count: int
    audit_id: str
    blockers: tuple[ProvisionalMembershipBlocker, ...]
    segments: tuple[StrictCoverageSegment, ...]
    greedy_cover: tuple[GreedyBlockerSelection, ...]
    blocked_days_by_membership: tuple[tuple[int, int], ...]
    unique_blocked_days_by_membership: tuple[tuple[int, int], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": STRICT_COVERAGE_SCHEMA_VERSION,
            "audit_id": self.audit_id,
            "universe_code": self.universe_code,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "day_count": self.day_count,
            "blocked_day_count": self.blocked_day_count,
            "strict_eligible_day_count": self.strict_eligible_day_count,
            "provisional_membership_count": self.provisional_membership_count,
            "blockers": [_blocker_dict(item) for item in self.blockers],
            "segments": [_segment_dict(item) for item in self.segments],
            "greedy_cover": [asdict(item) for item in self.greedy_cover],
            "blocked_days_by_membership": [
                {"membership_id": membership_id, "day_count": day_count}
                for membership_id, day_count in self.blocked_days_by_membership
            ],
            "unique_blocked_days_by_membership": [
                {"membership_id": membership_id, "day_count": day_count}
                for membership_id, day_count in self.unique_blocked_days_by_membership
            ],
        }


def _identity_dict(identity: IdentityContext) -> dict[str, object]:
    return {
        "symbol": identity.symbol,
        "effective_from": identity.effective_from.isoformat(),
        "effective_to": identity.effective_to.isoformat() if identity.effective_to else None,
        "verification_status": identity.verification_status,
        "source_hash": identity.source_hash,
    }


def _blocker_dict(blocker: ProvisionalMembershipBlocker) -> dict[str, object]:
    return {
        "membership_id": blocker.membership_id,
        "security_id": blocker.security_id,
        "cik": blocker.cik,
        "effective_from": blocker.effective_from.isoformat(),
        "effective_to": blocker.effective_to.isoformat() if blocker.effective_to else None,
        "source": blocker.source,
        "source_url": blocker.source_url,
        "source_hash": blocker.source_hash,
        "confidence": format(blocker.confidence, ".17g"),
        "identities": [_identity_dict(item) for item in blocker.identities],
    }


def _segment_dict(segment: StrictCoverageSegment) -> dict[str, object]:
    return {
        "effective_from": segment.effective_from.isoformat(),
        "effective_to": segment.effective_to.isoformat(),
        "day_count": segment.day_count,
        "blocker_ids": list(segment.blocker_ids),
    }


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clipped_interval(
    blocker: ProvisionalMembershipBlocker,
    *,
    window_start: date,
    window_end_exclusive: date,
) -> tuple[date, date] | None:
    start = max(blocker.effective_from, window_start)
    end = (
        window_end_exclusive
        if blocker.effective_to is None
        else min(blocker.effective_to, window_end_exclusive)
    )
    if end <= start:
        return None
    return start, end


def _build_segments(
    blockers: Sequence[ProvisionalMembershipBlocker],
    *,
    window_start: date,
    window_end: date,
) -> tuple[StrictCoverageSegment, ...]:
    window_end_exclusive = window_end + timedelta(days=1)
    clipped = {
        blocker.membership_id: interval
        for blocker in blockers
        if (
            interval := _clipped_interval(
                blocker,
                window_start=window_start,
                window_end_exclusive=window_end_exclusive,
            )
        )
        is not None
    }
    boundaries = {window_start, window_end_exclusive}
    for start, end in clipped.values():
        boundaries.update((start, end))
    ordered = sorted(boundaries)
    segments: list[StrictCoverageSegment] = []
    for start, end in zip(ordered, ordered[1:]):
        if end <= start:
            continue
        active = tuple(
            sorted(
                membership_id
                for membership_id, (blocker_start, blocker_end) in clipped.items()
                if blocker_start <= start < blocker_end
            )
        )
        segments.append(
            StrictCoverageSegment(
                effective_from=start,
                effective_to=end,
                day_count=(end - start).days,
                blocker_ids=active,
            )
        )
    return tuple(segments)


def _greedy_cover(
    segments: Sequence[StrictCoverageSegment],
) -> tuple[GreedyBlockerSelection, ...]:
    remaining = {index for index, segment in enumerate(segments) if segment.blocker_ids}
    selections: list[GreedyBlockerSelection] = []
    rank = 1
    while remaining:
        scores: Counter[int] = Counter()
        for index in remaining:
            segment = segments[index]
            for membership_id in segment.blocker_ids:
                scores[membership_id] += segment.day_count
        if not scores:
            break
        membership_id, newly_covered = min(
            scores.items(),
            key=lambda item: (-item[1], item[0]),
        )
        remaining = {
            index
            for index in remaining
            if membership_id not in segments[index].blocker_ids
        }
        remaining_days = sum(segments[index].day_count for index in remaining)
        selections.append(
            GreedyBlockerSelection(
                rank=rank,
                membership_id=membership_id,
                newly_covered_days=newly_covered,
                remaining_blocked_days=remaining_days,
            )
        )
        rank += 1
    return tuple(selections)


def build_strict_coverage_audit(
    blockers: Sequence[ProvisionalMembershipBlocker],
    *,
    universe_code: str,
    window_start: date,
    window_end: date,
) -> StrictCoverageAudit:
    """Measure exactly which provisional memberships invalidate each calendar interval."""
    if window_end < window_start:
        raise ValueError("window_end must be on or after window_start")
    normalized = universe_code.strip().lower()
    if not normalized:
        raise ValueError("universe_code is required")
    membership_ids = [item.membership_id for item in blockers]
    if len(set(membership_ids)) != len(membership_ids):
        raise ValueError("provisional membership IDs must be unique")

    ordered_blockers = tuple(
        sorted(
            blockers,
            key=lambda item: (
                item.effective_from,
                item.effective_to or date.max,
                item.security_id,
                item.membership_id,
            ),
        )
    )
    segments = _build_segments(
        ordered_blockers,
        window_start=window_start,
        window_end=window_end,
    )
    blocked_days = sum(segment.day_count for segment in segments if segment.blocker_ids)
    day_count = (window_end - window_start).days + 1

    by_membership: Counter[int] = Counter()
    unique_by_membership: Counter[int] = Counter()
    for segment in segments:
        for membership_id in segment.blocker_ids:
            by_membership[membership_id] += segment.day_count
        if len(segment.blocker_ids) == 1:
            unique_by_membership[segment.blocker_ids[0]] += segment.day_count

    blocked_days_by_membership = tuple(
        sorted(by_membership.items(), key=lambda item: (-item[1], item[0]))
    )
    unique_days_by_membership = tuple(
        sorted(unique_by_membership.items(), key=lambda item: (-item[1], item[0]))
    )
    greedy = _greedy_cover(segments)
    payload = {
        "schema_version": STRICT_COVERAGE_SCHEMA_VERSION,
        "universe_code": normalized,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "blockers": [_blocker_dict(item) for item in ordered_blockers],
        "segments": [_segment_dict(item) for item in segments],
        "greedy_cover": [asdict(item) for item in greedy],
    }
    return StrictCoverageAudit(
        universe_code=normalized,
        window_start=window_start,
        window_end=window_end,
        day_count=day_count,
        blocked_day_count=blocked_days,
        strict_eligible_day_count=day_count - blocked_days,
        provisional_membership_count=len(ordered_blockers),
        audit_id=_digest(payload),
        blockers=ordered_blockers,
        segments=segments,
        greedy_cover=greedy,
        blocked_days_by_membership=blocked_days_by_membership,
        unique_blocked_days_by_membership=unique_days_by_membership,
    )
