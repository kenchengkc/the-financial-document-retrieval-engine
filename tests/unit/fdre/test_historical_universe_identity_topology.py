from __future__ import annotations

import pytest

from fdre.research.historical_universe_identity_topology import (
    IdentityTopologyPeriod,
    MembershipTopologyPeriod,
    ResidualIdentityGap,
    ResidualIdentityTarget,
    build_residual_identity_topology,
)

AUDIT_ID = "a" * 64


def _identity(
    *,
    identity_id: int,
    security_id: int = 10,
    symbol: str = "ABC",
    start: str = "2020-01-01",
    end: str | None = None,
    status: str = "verified",
    source_hash: str | None = None,
) -> IdentityTopologyPeriod:
    return IdentityTopologyPeriod(
        identity_id=identity_id,
        security_id=security_id,
        symbol=symbol,
        name=None,
        exchange="NYSE",
        effective_from=start,
        effective_to=end,
        verification_status=status,
        source="fixture",
        source_url=None,
        source_observed_at="2026-01-01T00:00:00+00:00",
        source_hash=source_hash or f"{identity_id:064x}",
        confidence=1.0,
    )


def _membership(
    *,
    membership_id: int = 20,
    security_id: int = 10,
    start: str = "2020-01-01",
    end: str | None = None,
) -> MembershipTopologyPeriod:
    return MembershipTopologyPeriod(
        membership_id=membership_id,
        universe_code="sp500",
        security_id=security_id,
        effective_from=start,
        effective_to=end,
        verification_status="verified",
        source="fixture",
        source_url=None,
        source_observed_at="2026-01-01T00:00:00+00:00",
        source_hash=f"{membership_id:064x}",
        confidence=1.0,
    )


def _target(*, identity_id: int = 2, security_id: int = 10) -> ResidualIdentityTarget:
    target_hash = f"{identity_id:064x}"
    identities = (
        _identity(identity_id=1, security_id=security_id, end="2020-06-01"),
        _identity(
            identity_id=identity_id,
            security_id=security_id,
            symbol="XYZ",
            start="2020-06-01",
            status="provisional",
            source_hash=target_hash,
        ),
    )
    return ResidualIdentityTarget(
        identity_id=identity_id,
        security_id=security_id,
        cik="0000000123",
        symbol="XYZ",
        effective_from="2020-06-01",
        effective_to=None,
        source_hash=target_hash,
        issue_membership_ids=(20,),
        identity_periods=identities,
        memberships=(_membership(security_id=security_id),),
    )


def test_topology_is_deterministic_across_input_order() -> None:
    first_target = _target(identity_id=2, security_id=10)
    second_target = _target(identity_id=4, security_id=11)
    first = build_residual_identity_topology(
        audit_id=AUDIT_ID,
        targets=(second_target, first_target),
        gaps=(),
    )
    second = build_residual_identity_topology(
        audit_id=AUDIT_ID,
        targets=(first_target, second_target),
        gaps=(),
    )
    assert first == second
    assert [item.identity_id for item in first.targets] == [2, 4]


def test_target_must_remain_provisional() -> None:
    target = _target()
    verified_target = ResidualIdentityTarget(
        identity_id=target.identity_id,
        security_id=target.security_id,
        cik=target.cik,
        symbol=target.symbol,
        effective_from=target.effective_from,
        effective_to=target.effective_to,
        source_hash=target.source_hash,
        issue_membership_ids=target.issue_membership_ids,
        identity_periods=(
            target.identity_periods[0],
            _identity(
                identity_id=target.identity_id,
                symbol=target.symbol,
                start=target.effective_from,
                status="verified",
                source_hash=target.source_hash,
            ),
        ),
        memberships=target.memberships,
    )
    with pytest.raises(ValueError, match="is not provisional"):
        build_residual_identity_topology(
            audit_id=AUDIT_ID,
            targets=(verified_target,),
            gaps=(),
        )


def test_target_live_fields_are_bound_into_projection() -> None:
    target = _target()
    drifted = ResidualIdentityTarget(
        identity_id=target.identity_id,
        security_id=target.security_id,
        cik=target.cik,
        symbol="DIFFERENT",
        effective_from=target.effective_from,
        effective_to=target.effective_to,
        source_hash=target.source_hash,
        issue_membership_ids=target.issue_membership_ids,
        identity_periods=target.identity_periods,
        memberships=target.memberships,
    )
    with pytest.raises(ValueError, match="live row fields drifted"):
        build_residual_identity_topology(
            audit_id=AUDIT_ID,
            targets=(drifted,),
            gaps=(),
        )


def test_issue_memberships_must_exist_in_same_security_topology() -> None:
    target = _target()
    unknown = ResidualIdentityTarget(
        identity_id=target.identity_id,
        security_id=target.security_id,
        cik=target.cik,
        symbol=target.symbol,
        effective_from=target.effective_from,
        effective_to=target.effective_to,
        source_hash=target.source_hash,
        issue_membership_ids=(999,),
        identity_periods=target.identity_periods,
        memberships=target.memberships,
    )
    with pytest.raises(ValueError, match="unknown membership"):
        build_residual_identity_topology(
            audit_id=AUDIT_ID,
            targets=(unknown,),
            gaps=(),
        )


def test_gap_must_reference_same_security_membership() -> None:
    gap = ResidualIdentityGap(
        membership_id=20,
        security_id=10,
        cik="0000000123",
        effective_from="2020-06-01",
        effective_to="2020-06-03",
        identity_periods=(
            _identity(identity_id=1, end="2020-06-01"),
            _identity(identity_id=2, start="2020-06-03"),
        ),
        memberships=(_membership(membership_id=21),),
    )
    with pytest.raises(ValueError, match="missing from security topology"):
        build_residual_identity_topology(audit_id=AUDIT_ID, targets=(), gaps=(gap,))


def test_duplicate_target_ids_fail_closed() -> None:
    target = _target()
    with pytest.raises(ValueError, match="must be unique"):
        build_residual_identity_topology(
            audit_id=AUDIT_ID,
            targets=(target, target),
            gaps=(),
        )
