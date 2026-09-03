from __future__ import annotations

from datetime import date

from fdre.research.historical_universe_identity_strict_coverage import (
    IdentityCoverageIdentity,
    IdentityCoverageMembership,
    build_identity_strict_coverage_audit,
)

START = date(2020, 1, 1)
END = date(2020, 1, 10)


def _identity(
    *,
    identity_id: int = 1,
    symbol: str = "ABC",
    start: date = START,
    end: date | None = None,
    status: str = "verified",
) -> IdentityCoverageIdentity:
    return IdentityCoverageIdentity(
        identity_id=identity_id,
        symbol=symbol,
        effective_from=start,
        effective_to=end,
        verification_status=status,
        source_hash=f"{identity_id:064x}",
    )


def _membership(
    *,
    membership_id: int = 10,
    security_id: int = 20,
    start: date = START,
    end: date | None = None,
    status: str = "verified",
    identities: tuple[IdentityCoverageIdentity, ...] | None = None,
) -> IdentityCoverageMembership:
    return IdentityCoverageMembership(
        membership_id=membership_id,
        security_id=security_id,
        cik="0000000123",
        effective_from=start,
        effective_to=end,
        verification_status=status,
        source_hash=f"{membership_id:064x}",
        identities=(_identity(),) if identities is None else identities,
    )


def _audit(
    memberships: tuple[IdentityCoverageMembership, ...],
):  # type: ignore[no-untyped-def]
    return build_identity_strict_coverage_audit(
        memberships,
        universe_code="sp500",
        window_start=START,
        window_end=END,
    )


def test_one_verified_identity_is_fully_eligible() -> None:
    audit = _audit((_membership(),))
    assert audit.day_count == 10
    assert audit.blocked_day_count == 0
    assert audit.strict_eligible_day_count == 10
    assert not audit.issues


def test_provisional_membership_blocks_entire_interval() -> None:
    audit = _audit((_membership(status="provisional"),))
    assert audit.blocked_day_count == 10
    assert audit.issues[0].reason == "membership_not_verified"


def test_missing_identity_blocks() -> None:
    audit = _audit((_membership(identities=()),))
    assert audit.blocked_day_count == 10
    assert audit.issues[0].reason == "identity_missing"


def test_single_provisional_identity_blocks_and_is_reported() -> None:
    audit = _audit((_membership(identities=(_identity(status="provisional"),)),))
    assert audit.blocked_day_count == 10
    assert audit.issues[0].reason == "identity_not_verified"
    assert audit.relevant_provisional_identity_ids == (1,)


def test_verified_plus_provisional_competitor_is_ambiguous() -> None:
    audit = _audit(
        (
            _membership(
                identities=(
                    _identity(identity_id=1, status="verified"),
                    _identity(identity_id=2, symbol="XYZ", status="provisional"),
                )
            ),
        )
    )
    assert audit.blocked_day_count == 10
    assert audit.issues[0].reason == "identity_ambiguous"
    assert audit.relevant_provisional_identity_ids == (2,)


def test_adjacent_verified_identity_transition_is_eligible() -> None:
    pivot = date(2020, 1, 6)
    audit = _audit(
        (
            _membership(
                identities=(
                    _identity(identity_id=1, symbol="OLD", end=pivot),
                    _identity(identity_id=2, symbol="NEW", start=pivot),
                )
            ),
        )
    )
    assert audit.blocked_day_count == 0
    assert audit.strict_eligible_day_count == 10


def test_provisional_identity_outside_membership_is_irrelevant() -> None:
    membership = _membership(
        start=date(2020, 1, 5),
        identities=(
            _identity(identity_id=1, start=date(2020, 1, 5)),
            _identity(
                identity_id=2,
                start=START,
                end=date(2020, 1, 5),
                status="provisional",
            ),
        ),
    )
    audit = _audit((membership,))
    assert audit.blocked_day_count == 0
    assert audit.relevant_provisional_identity_ids == ()


def test_same_identity_can_support_split_memberships() -> None:
    shared = _identity(identity_id=5)
    audit = _audit(
        (
            _membership(
                membership_id=10,
                security_id=20,
                end=date(2020, 1, 5),
                identities=(shared,),
            ),
            _membership(
                membership_id=11,
                security_id=20,
                start=date(2020, 1, 5),
                identities=(shared,),
            ),
        )
    )
    assert audit.blocked_day_count == 0


def test_input_order_does_not_change_audit() -> None:
    memberships = (
        _membership(membership_id=11, security_id=21),
        _membership(membership_id=10, security_id=20),
    )
    first = _audit(memberships)
    second = _audit(tuple(reversed(memberships)))
    assert first == second
