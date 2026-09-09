"""Deterministic comparison of point-in-time universe snapshots by stable security identity."""

from __future__ import annotations

from dataclasses import dataclass

from fdre.research.historical_universe import UniverseSnapshot, UniverseSnapshotConstituent

_CONSTITUENT_FIELDS = (
    "cik",
    "symbol",
    "name",
    "exchange",
    "membership_effective_from",
    "identity_effective_from",
    "membership_source_hash",
    "identity_source_hash",
    "verification_status",
)


@dataclass(frozen=True, slots=True)
class UniverseConstituentChange:
    security_id: int
    changed_fields: tuple[str, ...]
    before: UniverseSnapshotConstituent
    after: UniverseSnapshotConstituent


@dataclass(frozen=True, slots=True)
class UniverseSnapshotDiff:
    universe_code: str
    from_snapshot_id: str
    to_snapshot_id: str
    from_as_of: str
    to_as_of: str
    includes_provisional: bool
    added: tuple[UniverseSnapshotConstituent, ...]
    removed: tuple[UniverseSnapshotConstituent, ...]
    changed: tuple[UniverseConstituentChange, ...]
    retained_count: int


def compare_universe_snapshots(
    before: UniverseSnapshot,
    after: UniverseSnapshot,
) -> UniverseSnapshotDiff:
    """Compare two replayable snapshots without collapsing securities by ticker."""

    if before.universe_code != after.universe_code:
        raise ValueError("universe snapshots must use the same universe_code")
    if before.includes_provisional != after.includes_provisional:
        raise ValueError("universe snapshots must use the same provisional-evidence mode")
    if after.as_of < before.as_of:
        raise ValueError("to snapshot must not precede from snapshot")

    before_by_security = {row.security_id: row for row in before.constituents}
    after_by_security = {row.security_id: row for row in after.constituents}
    if len(before_by_security) != len(before.constituents):
        raise ValueError("from snapshot contains duplicate stable security identities")
    if len(after_by_security) != len(after.constituents):
        raise ValueError("to snapshot contains duplicate stable security identities")

    before_ids = set(before_by_security)
    after_ids = set(after_by_security)
    added = tuple(after_by_security[item] for item in sorted(after_ids - before_ids))
    removed = tuple(before_by_security[item] for item in sorted(before_ids - after_ids))

    changes: list[UniverseConstituentChange] = []
    for security_id in sorted(before_ids & after_ids):
        before_row = before_by_security[security_id]
        after_row = after_by_security[security_id]
        changed_fields = tuple(
            field
            for field in _CONSTITUENT_FIELDS
            if getattr(before_row, field) != getattr(after_row, field)
        )
        if changed_fields:
            changes.append(
                UniverseConstituentChange(
                    security_id=security_id,
                    changed_fields=changed_fields,
                    before=before_row,
                    after=after_row,
                )
            )

    return UniverseSnapshotDiff(
        universe_code=before.universe_code,
        from_snapshot_id=before.snapshot_id,
        to_snapshot_id=after.snapshot_id,
        from_as_of=before.as_of.isoformat(),
        to_as_of=after.as_of.isoformat(),
        includes_provisional=before.includes_provisional,
        added=added,
        removed=removed,
        changed=tuple(changes),
        retained_count=len(before_ids & after_ids),
    )


def universe_diff_to_dict(diff: UniverseSnapshotDiff) -> dict[str, object]:
    """Serialize a snapshot diff while retaining source and identity provenance."""

    return {
        "schema_version": "fdre-hu3-universe-diff-v1",
        "universe_code": diff.universe_code,
        "from_snapshot_id": diff.from_snapshot_id,
        "to_snapshot_id": diff.to_snapshot_id,
        "from_as_of": diff.from_as_of,
        "to_as_of": diff.to_as_of,
        "includes_provisional": diff.includes_provisional,
        "summary": {
            "from_count": diff.retained_count + len(diff.removed),
            "to_count": diff.retained_count + len(diff.added),
            "added_count": len(diff.added),
            "removed_count": len(diff.removed),
            "changed_count": len(diff.changed),
            "retained_count": diff.retained_count,
        },
        "added": [_constituent_to_dict(row) for row in diff.added],
        "removed": [_constituent_to_dict(row) for row in diff.removed],
        "changed": [
            {
                "security_id": item.security_id,
                "changed_fields": list(item.changed_fields),
                "before": _constituent_to_dict(item.before),
                "after": _constituent_to_dict(item.after),
            }
            for item in diff.changed
        ],
    }


def _constituent_to_dict(row: UniverseSnapshotConstituent) -> dict[str, object]:
    return {
        "security_id": row.security_id,
        "cik": row.cik,
        "symbol": row.symbol,
        "name": row.name,
        "exchange": row.exchange,
        "membership_effective_from": row.membership_effective_from.isoformat(),
        "identity_effective_from": row.identity_effective_from.isoformat(),
        "membership_source_hash": row.membership_source_hash,
        "identity_source_hash": row.identity_source_hash,
        "verification_status": row.verification_status,
    }
