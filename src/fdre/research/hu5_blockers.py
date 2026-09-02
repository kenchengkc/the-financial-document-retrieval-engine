"""Deterministic attribution of strict Historical Universe blockers for HU-5."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from pathlib import Path

from fdre.research.hu5_universe import HU5UniverseRecords

HU5_BLOCKER_AUDIT_SCHEMA_VERSION = "fdre-hu5-strict-blocker-audit-v1"


@dataclass(frozen=True, slots=True)
class HU5MembershipBlocker:
    blocker_id: str
    security_id: int
    cik: str | None
    symbols: tuple[str, ...]
    effective_from: str
    effective_to: str | None
    source_hash: str
    active_day_count: int
    exclusive_day_count: int = 0


@dataclass(frozen=True, slots=True)
class HU5IdentityBlocker:
    blocker_id: str
    security_id: int
    cik: str
    symbol: str
    effective_from: str
    effective_to: str | None
    source_hash: str
    active_membership_day_count: int


@dataclass(frozen=True, slots=True)
class HU5BlockerSegment:
    start: str
    end_exclusive: str
    day_count: int
    membership_blocker_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HU5StrictBlockerAudit:
    universe_code: str
    input_provenance_id: str
    window_start: str
    window_end: str
    day_count: int
    membership_blocker_count: int
    latent_identity_blocker_count: int
    membership_blocked_day_count: int
    membership_unblocked_day_count: int
    projected_identity_blocked_day_count: int
    projected_strict_day_count_after_membership_only: int
    minimum_active_membership_blockers: int
    maximum_active_membership_blockers: int
    blocker_audit_id: str
    membership_blockers: tuple[HU5MembershipBlocker, ...]
    latent_identity_blockers: tuple[HU5IdentityBlocker, ...]
    segments: tuple[HU5BlockerSegment, ...]


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _end_exclusive(value: date | None, window_end_exclusive: date) -> date:
    return min(value, window_end_exclusive) if value is not None else window_end_exclusive


def _overlap(
    left_start: date,
    left_end: date | None,
    right_start: date,
    right_end: date | None,
) -> tuple[date, date] | None:
    right_end_value = right_end or date.max
    left_end_value = left_end or date.max
    start = max(left_start, right_start)
    end = min(left_end_value, right_end_value)
    return (start, end) if start < end else None


def _identity_labels(
    records: HU5UniverseRecords,
    *,
    security_id: int,
    interval_start: date,
    interval_end: date | None,
) -> tuple[str | None, tuple[str, ...]]:
    identities = [
        item
        for item in records.identities
        if item.security_id == security_id
        and _overlap(item.effective_from, item.effective_to, interval_start, interval_end)
        is not None
    ]
    ciks = sorted({item.cik for item in identities})
    symbols = tuple(sorted({item.symbol.upper() for item in identities}))
    cik = ciks[0] if len(ciks) == 1 else None
    return cik, symbols


def _membership_blockers(
    records: HU5UniverseRecords,
    *,
    window_start: date,
    window_end: date,
) -> tuple[HU5MembershipBlocker, ...]:
    window_end_exclusive = window_end + timedelta(days=1)
    blockers: list[HU5MembershipBlocker] = []
    for item in records.memberships:
        if item.verification_status != "provisional":
            continue
        overlap = _overlap(
            item.effective_from,
            item.effective_to,
            window_start,
            window_end_exclusive,
        )
        if overlap is None:
            continue
        start, end = overlap
        cik, symbols = _identity_labels(
            records,
            security_id=item.security_id,
            interval_start=item.effective_from,
            interval_end=item.effective_to,
        )
        identity = {
            "kind": "membership",
            "universe_code": item.universe_code,
            "security_id": item.security_id,
            "effective_from": item.effective_from.isoformat(),
            "effective_to": item.effective_to.isoformat() if item.effective_to else None,
            "source_hash": item.source_hash,
        }
        blockers.append(
            HU5MembershipBlocker(
                blocker_id=_digest(identity),
                security_id=item.security_id,
                cik=cik,
                symbols=symbols,
                effective_from=item.effective_from.isoformat(),
                effective_to=item.effective_to.isoformat() if item.effective_to else None,
                source_hash=item.source_hash,
                active_day_count=(end - start).days,
            )
        )
    return tuple(sorted(blockers, key=lambda item: (item.effective_from, item.security_id)))


def _membership_segments(
    blockers: tuple[HU5MembershipBlocker, ...],
    *,
    window_start: date,
    window_end: date,
) -> tuple[tuple[HU5MembershipBlocker, ...], tuple[HU5BlockerSegment, ...]]:
    window_end_exclusive = window_end + timedelta(days=1)
    events: dict[date, list[tuple[bool, str]]] = {}
    for item in blockers:
        start = max(date.fromisoformat(item.effective_from), window_start)
        raw_end = date.fromisoformat(item.effective_to) if item.effective_to else None
        end = _end_exclusive(raw_end, window_end_exclusive)
        if start >= end:
            continue
        events.setdefault(start, []).append((True, item.blocker_id))
        events.setdefault(end, []).append((False, item.blocker_id))

    active: set[str] = set()
    cursor = window_start
    segments: list[HU5BlockerSegment] = []
    exclusive_days: dict[str, int] = {item.blocker_id: 0 for item in blockers}

    for boundary in sorted(set(events) | {window_start, window_end_exclusive}):
        if boundary > cursor:
            ids = tuple(sorted(active))
            days = (boundary - cursor).days
            segments.append(
                HU5BlockerSegment(
                    start=cursor.isoformat(),
                    end_exclusive=boundary.isoformat(),
                    day_count=days,
                    membership_blocker_ids=ids,
                )
            )
            if len(ids) == 1:
                exclusive_days[ids[0]] += days
            cursor = boundary
        changes = events.get(boundary, ())
        for is_add, blocker_id in changes:
            if not is_add:
                active.discard(blocker_id)
        for is_add, blocker_id in changes:
            if is_add:
                active.add(blocker_id)

    enriched = tuple(
        replace(item, exclusive_day_count=exclusive_days[item.blocker_id])
        for item in blockers
    )
    return enriched, tuple(segments)


def _identity_blockers(
    records: HU5UniverseRecords,
    *,
    window_start: date,
    window_end: date,
) -> tuple[HU5IdentityBlocker, ...]:
    window_end_exclusive = window_end + timedelta(days=1)
    blockers: list[HU5IdentityBlocker] = []
    for identity in records.identities:
        if identity.verification_status != "provisional":
            continue
        spans: list[tuple[date, date]] = []
        for membership in records.memberships:
            if membership.security_id != identity.security_id:
                continue
            overlap = _overlap(
                identity.effective_from,
                identity.effective_to,
                membership.effective_from,
                membership.effective_to,
            )
            if overlap is None:
                continue
            overlap = _overlap(overlap[0], overlap[1], window_start, window_end_exclusive)
            if overlap is not None:
                spans.append(overlap)
        if not spans:
            continue

        merged: list[tuple[date, date]] = []
        for start, end in sorted(spans):
            if not merged or merged[-1][1] < start:
                merged.append((start, end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        active_days = sum((end - start).days for start, end in merged)
        identity_payload = {
            "kind": "identity",
            "security_id": identity.security_id,
            "cik": identity.cik,
            "symbol": identity.symbol.upper(),
            "effective_from": identity.effective_from.isoformat(),
            "effective_to": identity.effective_to.isoformat() if identity.effective_to else None,
            "source_hash": identity.source_hash,
        }
        blockers.append(
            HU5IdentityBlocker(
                blocker_id=_digest(identity_payload),
                security_id=identity.security_id,
                cik=identity.cik,
                symbol=identity.symbol.upper(),
                effective_from=identity.effective_from.isoformat(),
                effective_to=identity.effective_to.isoformat() if identity.effective_to else None,
                source_hash=identity.source_hash,
                active_membership_day_count=active_days,
            )
        )
    return tuple(
        sorted(blockers, key=lambda item: (item.effective_from, item.security_id, item.symbol))
    )


def _union_identity_blocked_days(
    blockers: tuple[HU5IdentityBlocker, ...],
    *,
    records: HU5UniverseRecords,
    window_start: date,
    window_end: date,
) -> int:
    window_end_exclusive = window_end + timedelta(days=1)
    spans: list[tuple[date, date]] = []
    blocker_keys = {
        (item.security_id, item.symbol, item.effective_from, item.effective_to, item.source_hash)
        for item in blockers
    }
    for identity in records.identities:
        key = (
            identity.security_id,
            identity.symbol.upper(),
            identity.effective_from.isoformat(),
            identity.effective_to.isoformat() if identity.effective_to else None,
            identity.source_hash,
        )
        if key not in blocker_keys:
            continue
        for membership in records.memberships:
            if membership.security_id != identity.security_id:
                continue
            overlap = _overlap(
                identity.effective_from,
                identity.effective_to,
                membership.effective_from,
                membership.effective_to,
            )
            if overlap is None:
                continue
            overlap = _overlap(overlap[0], overlap[1], window_start, window_end_exclusive)
            if overlap is not None:
                spans.append(overlap)
    if not spans:
        return 0
    merged: list[tuple[date, date]] = []
    for start, end in sorted(spans):
        if not merged or merged[-1][1] < start:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return sum((end - start).days for start, end in merged)


def build_hu5_strict_blocker_audit(
    records: HU5UniverseRecords,
    *,
    universe_code: str,
    input_provenance_id: str,
    window_start: date,
    window_end: date,
) -> HU5StrictBlockerAudit:
    """Attribute every currently known date-wide HU-5 strictness blocker."""
    if window_end < window_start:
        raise ValueError("window_end must be on or after window_start")
    day_count = (window_end - window_start).days + 1

    membership_blockers = _membership_blockers(
        records,
        window_start=window_start,
        window_end=window_end,
    )
    membership_blockers, segments = _membership_segments(
        membership_blockers,
        window_start=window_start,
        window_end=window_end,
    )
    identity_blockers = _identity_blockers(
        records,
        window_start=window_start,
        window_end=window_end,
    )
    membership_blocked_days = sum(
        segment.day_count for segment in segments if segment.membership_blocker_ids
    )
    identity_blocked_days = _union_identity_blocked_days(
        identity_blockers,
        records=records,
        window_start=window_start,
        window_end=window_end,
    )
    blocker_counts = [len(segment.membership_blocker_ids) for segment in segments]
    payload = {
        "schema_version": HU5_BLOCKER_AUDIT_SCHEMA_VERSION,
        "universe_code": universe_code.strip().lower(),
        "input_provenance_id": input_provenance_id,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "membership_blockers": [asdict(item) for item in membership_blockers],
        "latent_identity_blockers": [asdict(item) for item in identity_blockers],
        "segments": [asdict(item) for item in segments],
    }
    return HU5StrictBlockerAudit(
        universe_code=universe_code.strip().lower(),
        input_provenance_id=input_provenance_id,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        day_count=day_count,
        membership_blocker_count=len(membership_blockers),
        latent_identity_blocker_count=len(identity_blockers),
        membership_blocked_day_count=membership_blocked_days,
        membership_unblocked_day_count=day_count - membership_blocked_days,
        projected_identity_blocked_day_count=identity_blocked_days,
        projected_strict_day_count_after_membership_only=day_count - identity_blocked_days,
        minimum_active_membership_blockers=min(blocker_counts, default=0),
        maximum_active_membership_blockers=max(blocker_counts, default=0),
        blocker_audit_id=_digest(payload),
        membership_blockers=membership_blockers,
        latent_identity_blockers=identity_blockers,
        segments=segments,
    )


def write_hu5_strict_blocker_audit(
    path: str | Path,
    audit: HU5StrictBlockerAudit,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": HU5_BLOCKER_AUDIT_SCHEMA_VERSION,
        "blocker_audit_id": audit.blocker_audit_id,
        **{key: value for key, value in asdict(audit).items() if key != "blocker_audit_id"},
    }
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return destination
