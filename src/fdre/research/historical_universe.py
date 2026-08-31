"""Point-in-time historical security-universe contracts.

Historical Universe v1 deliberately separates issuer identity (SEC CIK/company) from
listed-security identity so simultaneous share classes do not collapse into one ticker.
All effective intervals are half-open: ``[effective_from, effective_to)``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

VerificationStatus = Literal["verified", "provisional", "rejected"]
_ALLOWED_STATUSES = frozenset({"verified", "provisional", "rejected"})
_SNAPSHOT_SCHEMA_VERSION = "fdre-historical-universe-v1"


def _validate_interval(effective_from: date, effective_to: date | None) -> None:
    if effective_to is not None and effective_to <= effective_from:
        raise ValueError("effective_to must be later than effective_from")


def _validate_confidence(confidence: float) -> None:
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0.0 and 1.0")


def _validate_status(status: str) -> None:
    if status not in _ALLOWED_STATUSES:
        raise ValueError(f"unsupported verification status: {status}")


def _is_active(effective_from: date, effective_to: date | None, as_of: date) -> bool:
    return effective_from <= as_of and (effective_to is None or as_of < effective_to)


@dataclass(frozen=True, slots=True)
class SecurityIdentityRecord:
    """One symbol/name/exchange identity period for a stable security."""

    security_id: int
    cik: str
    symbol: str
    effective_from: date
    effective_to: date | None
    source_hash: str
    verification_status: VerificationStatus = "verified"
    confidence: float = 1.0
    name: str | None = None
    exchange: str | None = None

    def __post_init__(self) -> None:
        if self.security_id <= 0:
            raise ValueError("security_id must be positive")
        if not self.cik.strip():
            raise ValueError("cik is required")
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if not self.source_hash.strip():
            raise ValueError("source_hash is required")
        _validate_interval(self.effective_from, self.effective_to)
        _validate_confidence(self.confidence)
        _validate_status(self.verification_status)


@dataclass(frozen=True, slots=True)
class UniverseMembershipRecord:
    """One security's membership period in a named universe."""

    universe_code: str
    security_id: int
    effective_from: date
    effective_to: date | None
    source_hash: str
    verification_status: VerificationStatus = "verified"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not self.universe_code.strip():
            raise ValueError("universe_code is required")
        if self.security_id <= 0:
            raise ValueError("security_id must be positive")
        if not self.source_hash.strip():
            raise ValueError("source_hash is required")
        _validate_interval(self.effective_from, self.effective_to)
        _validate_confidence(self.confidence)
        _validate_status(self.verification_status)


@dataclass(frozen=True, slots=True)
class UniverseSnapshotConstituent:
    """Resolved security identity included in a PIT universe snapshot."""

    security_id: int
    cik: str
    symbol: str
    name: str | None
    exchange: str | None
    membership_effective_from: date
    identity_effective_from: date
    membership_source_hash: str
    identity_source_hash: str
    verification_status: VerificationStatus


@dataclass(frozen=True, slots=True)
class UniverseSnapshot:
    """Deterministic point-in-time universe with a replayable content hash."""

    universe_code: str
    as_of: date
    constituents: tuple[UniverseSnapshotConstituent, ...]
    snapshot_id: str
    includes_provisional: bool


def _eligible_status(status: VerificationStatus, include_provisional: bool) -> bool:
    if status == "verified":
        return True
    return include_provisional and status == "provisional"


def _canonical_snapshot_payload(
    universe_code: str,
    as_of: date,
    constituents: Sequence[UniverseSnapshotConstituent],
    *,
    include_provisional: bool,
) -> dict[str, object]:
    return {
        "schema_version": _SNAPSHOT_SCHEMA_VERSION,
        "universe_code": universe_code,
        "as_of": as_of.isoformat(),
        "include_provisional": include_provisional,
        "constituents": [
            {
                "cik": item.cik,
                "symbol": item.symbol,
                "name": item.name,
                "exchange": item.exchange,
                "membership_effective_from": item.membership_effective_from.isoformat(),
                "identity_effective_from": item.identity_effective_from.isoformat(),
                "membership_source_hash": item.membership_source_hash,
                "identity_source_hash": item.identity_source_hash,
                "verification_status": item.verification_status,
            }
            for item in constituents
        ],
    }


def _snapshot_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_universe_snapshot(
    *,
    universe_code: str,
    as_of: date,
    memberships: Sequence[UniverseMembershipRecord],
    identities: Sequence[SecurityIdentityRecord],
    include_provisional: bool = False,
) -> UniverseSnapshot:
    """Resolve a strict PIT universe snapshot.

    Rejected records never participate. By default, an active provisional membership is
    treated as unresolved evidence and causes the build to fail rather than silently shrinking
    the universe. ``include_provisional=True`` is therefore an explicit research choice.

    Exactly one active eligible membership and one active eligible security identity must exist
    for every included security. Overlap or missing identity fails closed.
    """

    normalized_universe = universe_code.strip().lower()
    if not normalized_universe:
        raise ValueError("universe_code is required")

    active_memberships = [
        membership
        for membership in memberships
        if membership.universe_code.strip().lower() == normalized_universe
        and membership.verification_status != "rejected"
        and _is_active(membership.effective_from, membership.effective_to, as_of)
    ]

    if not include_provisional and any(
        membership.verification_status == "provisional"
        for membership in active_memberships
    ):
        raise ValueError(
            "active provisional membership requires include_provisional=True or verification"
        )

    eligible_memberships = [
        membership
        for membership in active_memberships
        if _eligible_status(membership.verification_status, include_provisional)
    ]

    membership_by_security: dict[int, UniverseMembershipRecord] = {}
    for membership in eligible_memberships:
        if membership.security_id in membership_by_security:
            raise ValueError(
                f"overlapping active memberships for security_id={membership.security_id}"
            )
        membership_by_security[membership.security_id] = membership

    active_identity_by_security: dict[int, list[SecurityIdentityRecord]] = {}
    for identity in identities:
        if identity.verification_status == "rejected":
            continue
        if not _is_active(identity.effective_from, identity.effective_to, as_of):
            continue
        active_identity_by_security.setdefault(identity.security_id, []).append(identity)

    constituents: list[UniverseSnapshotConstituent] = []
    for security_id, membership in membership_by_security.items():
        matching_identities = active_identity_by_security.get(security_id, [])
        if len(matching_identities) != 1:
            if not matching_identities:
                raise ValueError(
                    f"no active identity for security_id={security_id} as_of={as_of}"
                )
            raise ValueError(
                f"overlapping active identities for security_id={security_id} as_of={as_of}"
            )

        identity = matching_identities[0]
        if not _eligible_status(identity.verification_status, include_provisional):
            raise ValueError(
                "active provisional identity requires include_provisional=True or verification"
            )
        status: VerificationStatus = (
            "provisional"
            if "provisional"
            in {membership.verification_status, identity.verification_status}
            else "verified"
        )
        constituents.append(
            UniverseSnapshotConstituent(
                security_id=security_id,
                cik=identity.cik,
                symbol=identity.symbol,
                name=identity.name,
                exchange=identity.exchange,
                membership_effective_from=membership.effective_from,
                identity_effective_from=identity.effective_from,
                membership_source_hash=membership.source_hash,
                identity_source_hash=identity.source_hash,
                verification_status=status,
            )
        )

    constituents.sort(
        key=lambda item: (
            item.cik,
            item.symbol,
            item.membership_effective_from,
            item.identity_effective_from,
        )
    )
    frozen_constituents = tuple(constituents)
    payload = _canonical_snapshot_payload(
        normalized_universe,
        as_of,
        frozen_constituents,
        include_provisional=include_provisional,
    )
    return UniverseSnapshot(
        universe_code=normalized_universe,
        as_of=as_of,
        constituents=frozen_constituents,
        snapshot_id=_snapshot_hash(payload),
        includes_provisional=include_provisional,
    )
