from __future__ import annotations

from datetime import date

from fdre.research.historical_universe import SecurityIdentityRecord, UniverseMembershipRecord
from fdre.research.hu5_blockers import build_hu5_strict_blocker_audit
from fdre.research.hu5_universe import HU5UniverseRecords


def _membership(
    security_id: int,
    start: date,
    end: date | None,
    *,
    status: str = "provisional",
) -> UniverseMembershipRecord:
    return UniverseMembershipRecord(
        universe_code="sp500",
        security_id=security_id,
        effective_from=start,
        effective_to=end,
        source_hash=f"membership-{security_id}-{start.isoformat()}",
        verification_status=status,  # type: ignore[arg-type]
        confidence=1.0 if status == "verified" else 0.85,
    )


def _identity(
    security_id: int,
    symbol: str,
    start: date,
    end: date | None,
    *,
    status: str = "verified",
) -> SecurityIdentityRecord:
    return SecurityIdentityRecord(
        security_id=security_id,
        cik=f"{security_id:010d}",
        symbol=symbol,
        effective_from=start,
        effective_to=end,
        source_hash=f"identity-{security_id}-{start.isoformat()}",
        verification_status=status,  # type: ignore[arg-type]
        confidence=1.0 if status == "verified" else 0.85,
    )


def test_blocker_audit_attributes_half_open_segments_and_exclusive_days() -> None:
    records = HU5UniverseRecords(
        memberships=(
            _membership(1, date(2020, 1, 1), date(2020, 1, 6)),
            _membership(2, date(2020, 1, 4), date(2020, 1, 9)),
        ),
        identities=(
            _identity(1, "AAA", date(2019, 1, 1), None),
            _identity(2, "BBB", date(2019, 1, 1), None),
        ),
    )

    audit = build_hu5_strict_blocker_audit(
        records,
        universe_code="sp500",
        input_provenance_id="input",
        window_start=date(2020, 1, 1),
        window_end=date(2020, 1, 10),
    )

    assert audit.membership_blocker_count == 2
    assert audit.membership_blocked_day_count == 8
    assert audit.membership_unblocked_day_count == 2
    assert audit.minimum_active_membership_blockers == 0
    assert audit.maximum_active_membership_blockers == 2
    by_symbol = {item.symbols[0]: item for item in audit.membership_blockers}
    assert by_symbol["AAA"].active_day_count == 5
    assert by_symbol["AAA"].exclusive_day_count == 3
    assert by_symbol["BBB"].active_day_count == 5
    assert by_symbol["BBB"].exclusive_day_count == 3
    assert [
        (item.start, item.end_exclusive, len(item.membership_blocker_ids))
        for item in audit.segments
    ] == [
        ("2020-01-01", "2020-01-04", 1),
        ("2020-01-04", "2020-01-06", 2),
        ("2020-01-06", "2020-01-09", 1),
        ("2020-01-09", "2020-01-11", 0),
    ]


def test_blocker_audit_exposes_identity_debt_after_membership_remediation() -> None:
    records = HU5UniverseRecords(
        memberships=(
            _membership(
                1,
                date(2020, 1, 1),
                None,
                status="verified",
            ),
        ),
        identities=(
            _identity(
                1,
                "AAA",
                date(2020, 1, 3),
                date(2020, 1, 8),
                status="provisional",
            ),
        ),
    )

    audit = build_hu5_strict_blocker_audit(
        records,
        universe_code="sp500",
        input_provenance_id="input",
        window_start=date(2020, 1, 1),
        window_end=date(2020, 1, 10),
    )

    assert audit.membership_blocker_count == 0
    assert audit.membership_blocked_day_count == 0
    assert audit.latent_identity_blocker_count == 1
    assert audit.latent_identity_blockers[0].active_membership_day_count == 5
    assert audit.projected_identity_blocked_day_count == 5
    assert audit.projected_strict_day_count_after_membership_only == 5


def test_blocker_audit_id_is_deterministic() -> None:
    records = HU5UniverseRecords(
        memberships=(_membership(1, date(2020, 1, 1), None),),
        identities=(_identity(1, "AAA", date(2020, 1, 1), None),),
    )
    first = build_hu5_strict_blocker_audit(
        records,
        universe_code="sp500",
        input_provenance_id="input",
        window_start=date(2020, 1, 1),
        window_end=date(2020, 1, 10),
    )
    second = build_hu5_strict_blocker_audit(
        records,
        universe_code="sp500",
        input_provenance_id="input",
        window_start=date(2020, 1, 1),
        window_end=date(2020, 1, 10),
    )

    assert first.blocker_audit_id == second.blocker_audit_id
