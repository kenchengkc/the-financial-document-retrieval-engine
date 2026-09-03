from datetime import date

import pytest

from fdre.research.historical_universe import (
    SecurityIdentityRecord,
    UniverseMembershipRecord,
    build_universe_snapshot,
)


def _identity(
    security_id: int,
    symbol: str,
    start: date,
    end: date | None = None,
    *,
    cik: str | None = None,
    source_hash: str | None = None,
    status: str = "verified",
) -> SecurityIdentityRecord:
    return SecurityIdentityRecord(
        security_id=security_id,
        cik=cik or f"000000000{security_id}",
        symbol=symbol,
        effective_from=start,
        effective_to=end,
        source_hash=source_hash or f"identity-{security_id}-{symbol}",
        verification_status=status,  # type: ignore[arg-type]
        name=f"{symbol} Corp",
        exchange="NYSE",
    )


def _membership(
    security_id: int,
    start: date,
    end: date | None = None,
    *,
    source_hash: str | None = None,
    status: str = "verified",
) -> UniverseMembershipRecord:
    return UniverseMembershipRecord(
        universe_code="sp500",
        security_id=security_id,
        effective_from=start,
        effective_to=end,
        source_hash=source_hash or f"membership-{security_id}",
        verification_status=status,  # type: ignore[arg-type]
    )


def test_snapshot_uses_half_open_membership_intervals() -> None:
    old_security = _membership(1, date(2015, 1, 1), date(2020, 3, 20))
    new_security = _membership(2, date(2020, 3, 20))
    identities = [
        _identity(1, "OLD", date(2015, 1, 1), date(2020, 3, 20)),
        _identity(2, "NEW", date(2020, 3, 20)),
    ]

    before = build_universe_snapshot(
        universe_code="sp500",
        as_of=date(2020, 3, 19),
        memberships=[old_security, new_security],
        identities=identities,
    )
    on_change = build_universe_snapshot(
        universe_code="sp500",
        as_of=date(2020, 3, 20),
        memberships=[old_security, new_security],
        identities=identities,
    )

    assert [row.symbol for row in before.constituents] == ["OLD"]
    assert [row.symbol for row in on_change.constituents] == ["NEW"]


def test_future_addition_cannot_leak_into_past_snapshot() -> None:
    memberships = [_membership(1, date(2023, 6, 1))]
    identities = [_identity(1, "LATE", date(2023, 6, 1))]

    snapshot = build_universe_snapshot(
        universe_code="sp500",
        as_of=date(2020, 6, 1),
        memberships=memberships,
        identities=identities,
    )

    assert snapshot.constituents == ()


def test_active_provisional_membership_fails_closed_by_default() -> None:
    memberships = [_membership(1, date(2020, 1, 1), status="provisional")]
    identities = [_identity(1, "ABC", date(2020, 1, 1), status="provisional")]

    with pytest.raises(ValueError, match="active provisional membership"):
        build_universe_snapshot(
            universe_code="sp500",
            as_of=date(2021, 1, 1),
            memberships=memberships,
            identities=identities,
        )

    snapshot = build_universe_snapshot(
        universe_code="sp500",
        as_of=date(2021, 1, 1),
        memberships=memberships,
        identities=identities,
        include_provisional=True,
    )
    assert snapshot.constituents[0].verification_status == "provisional"
    assert snapshot.includes_provisional is True


def test_overlapping_memberships_fail_closed() -> None:
    memberships = [
        _membership(1, date(2019, 1, 1), date(2022, 1, 1), source_hash="first"),
        _membership(1, date(2020, 1, 1), date(2023, 1, 1), source_hash="second"),
    ]

    with pytest.raises(ValueError, match="overlapping active memberships"):
        build_universe_snapshot(
            universe_code="sp500",
            as_of=date(2021, 1, 1),
            memberships=memberships,
            identities=[_identity(1, "ABC", date(2019, 1, 1))],
        )


def test_missing_or_overlapping_identity_fails_closed() -> None:
    membership = _membership(1, date(2020, 1, 1))

    with pytest.raises(ValueError, match="no active identity"):
        build_universe_snapshot(
            universe_code="sp500",
            as_of=date(2021, 1, 1),
            memberships=[membership],
            identities=[],
        )

    with pytest.raises(ValueError, match="overlapping active identities"):
        build_universe_snapshot(
            universe_code="sp500",
            as_of=date(2021, 1, 1),
            memberships=[membership],
            identities=[
                _identity(1, "ABC", date(2019, 1, 1), source_hash="one"),
                _identity(1, "XYZ", date(2020, 1, 1), source_hash="two"),
            ],
        )


def test_provisional_identity_overlap_cannot_hide_in_strict_snapshot() -> None:
    membership = _membership(1, date(2020, 1, 1))

    with pytest.raises(ValueError, match="active provisional identity"):
        build_universe_snapshot(
            universe_code="sp500",
            as_of=date(2021, 1, 1),
            memberships=[membership],
            identities=[
                _identity(
                    1,
                    "ABC",
                    date(2020, 1, 1),
                    source_hash="provisional",
                    status="provisional",
                )
            ],
        )

    with pytest.raises(ValueError, match="overlapping active identities"):
        build_universe_snapshot(
            universe_code="sp500",
            as_of=date(2021, 1, 1),
            memberships=[membership],
            identities=[
                _identity(1, "ABC", date(2020, 1, 1), source_hash="verified"),
                _identity(
                    1,
                    "XYZ",
                    date(2020, 6, 1),
                    source_hash="provisional",
                    status="provisional",
                ),
            ],
        )


def test_snapshot_hash_is_order_independent_and_provenance_sensitive() -> None:
    memberships = [
        _membership(1, date(2020, 1, 1), source_hash="membership-a"),
        _membership(2, date(2020, 1, 1), source_hash="membership-b"),
    ]
    identities = [
        _identity(1, "AAA", date(2020, 1, 1), source_hash="identity-a"),
        _identity(2, "BBB", date(2020, 1, 1), source_hash="identity-b"),
    ]

    first = build_universe_snapshot(
        universe_code="SP500",
        as_of=date(2021, 1, 1),
        memberships=memberships,
        identities=identities,
    )
    reordered = build_universe_snapshot(
        universe_code="sp500",
        as_of=date(2021, 1, 1),
        memberships=list(reversed(memberships)),
        identities=list(reversed(identities)),
    )
    changed_provenance = build_universe_snapshot(
        universe_code="sp500",
        as_of=date(2021, 1, 1),
        memberships=[memberships[0], _membership(2, date(2020, 1, 1), source_hash="changed")],
        identities=identities,
    )

    assert first.snapshot_id == reordered.snapshot_id
    assert first.snapshot_id != changed_provenance.snapshot_id
    assert [row.symbol for row in first.constituents] == ["AAA", "BBB"]


def test_record_validation_rejects_bad_ranges_and_confidence() -> None:
    with pytest.raises(ValueError, match="effective_to"):
        _membership(1, date(2020, 1, 2), date(2020, 1, 2))

    with pytest.raises(ValueError, match="confidence"):
        UniverseMembershipRecord(
            universe_code="sp500",
            security_id=1,
            effective_from=date(2020, 1, 1),
            effective_to=None,
            source_hash="source",
            confidence=1.1,
        )
