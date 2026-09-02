from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast

from fdre.research.event_study import FilingEvent
from fdre.research.historical_universe import (
    SecurityIdentityRecord,
    UniverseMembershipRecord,
    VerificationStatus,
)
from fdre.research.hu5_universe import (
    HU5UniverseRecords,
    build_hu5_universe_gate,
    resolve_hu5_events,
)


def _membership(
    security_id: int,
    *,
    status: str = "verified",
    source_hash: str | None = None,
) -> UniverseMembershipRecord:
    return UniverseMembershipRecord(
        universe_code="sp500",
        security_id=security_id,
        effective_from=date(2020, 1, 1),
        effective_to=None,
        source_hash=source_hash or f"membership-{security_id}",
        verification_status=cast(VerificationStatus, status),
    )


def _identity(
    security_id: int,
    cik: str,
    symbol: str,
    *,
    status: str = "verified",
    source_hash: str | None = None,
) -> SecurityIdentityRecord:
    return SecurityIdentityRecord(
        security_id=security_id,
        cik=cik,
        symbol=symbol,
        effective_from=date(2020, 1, 1),
        effective_to=None,
        source_hash=source_hash or f"identity-{security_id}",
        verification_status=cast(VerificationStatus, status),
    )


def test_one_provisional_membership_invalidates_the_entire_strict_date() -> None:
    records = HU5UniverseRecords(
        memberships=(
            _membership(1),
            _membership(2, status="provisional"),
        ),
        identities=(
            _identity(1, "0000000001", "AAA"),
            _identity(2, "0000000002", "BBB"),
        ),
    )

    gate = build_hu5_universe_gate(
        records,
        universe_code="sp500",
        window_start=date(2020, 6, 1),
        window_end=date(2020, 6, 1),
    )

    assert gate.day_count == 1
    assert gate.strict_eligible_day_count == 0
    assert gate.invalid_day_count == 1
    assert gate.dates[0].eligible is False
    assert "active provisional membership" in str(gate.dates[0].error)


def test_gate_identity_changes_when_source_provenance_changes() -> None:
    first = HU5UniverseRecords(
        memberships=(_membership(1, source_hash="membership-a"),),
        identities=(_identity(1, "0000000001", "AAA", source_hash="identity-a"),),
    )
    second = HU5UniverseRecords(
        memberships=(_membership(1, source_hash="membership-b"),),
        identities=(_identity(1, "0000000001", "AAA", source_hash="identity-a"),),
    )

    first_gate = build_hu5_universe_gate(
        first,
        universe_code="sp500",
        window_start=date(2020, 6, 1),
        window_end=date(2020, 6, 1),
    )
    second_gate = build_hu5_universe_gate(
        second,
        universe_code="sp500",
        window_start=date(2020, 6, 1),
        window_end=date(2020, 6, 1),
    )

    assert first_gate.strict_eligible_day_count == 1
    assert second_gate.strict_eligible_day_count == 1
    assert first_gate.input_provenance_id != second_gate.input_provenance_id
    assert first_gate.gate_manifest_id != second_gate.gate_manifest_id


def test_event_uses_verified_historical_symbol_and_source_hashes() -> None:
    records = HU5UniverseRecords(
        memberships=(_membership(1),),
        identities=(_identity(1, "0000000001", "OLD"),),
    )
    gate = build_hu5_universe_gate(
        records,
        universe_code="sp500",
        window_start=date(2020, 6, 1),
        window_end=date(2020, 6, 1),
    )
    event = FilingEvent(
        ticker="CURRENT",
        accession_number="0001-20-000001",
        available_at=datetime(2020, 6, 1, 12, tzinfo=UTC),
        max_source_available_at=datetime(2020, 6, 1, 12, tzinfo=UTC),
        feature_value=1.0,
    )

    resolved = resolve_hu5_events(
        [event],
        cik_by_accession={event.accession_number: "0000000001"},
        records=records,
        gate=gate,
    )

    assert len(resolved.events) == 1
    assert resolved.events[0].ticker == "OLD"
    assert resolved.lineage[0].membership_source_hash == "membership-1"
    assert resolved.lineage[0].identity_source_hash == "identity-1"
    assert resolved.lineage[0].snapshot_id == gate.dates[0].snapshot_id
    assert not resolved.ambiguous_accessions


def test_event_share_class_ambiguity_fails_closed() -> None:
    records = HU5UniverseRecords(
        memberships=(_membership(1), _membership(2)),
        identities=(
            _identity(1, "0000000001", "AAA"),
            _identity(2, "0000000001", "AAB"),
        ),
    )
    gate = build_hu5_universe_gate(
        records,
        universe_code="sp500",
        window_start=date(2020, 6, 1),
        window_end=date(2020, 6, 1),
    )
    event = FilingEvent(
        ticker="CURRENT",
        accession_number="0001-20-000001",
        available_at=datetime(2020, 6, 1, 12, tzinfo=UTC),
        max_source_available_at=datetime(2020, 6, 1, 12, tzinfo=UTC),
        feature_value=1.0,
    )

    resolved = resolve_hu5_events(
        [event],
        cik_by_accession={event.accession_number: "0000000001"},
        records=records,
        gate=gate,
    )

    assert not resolved.events
    assert resolved.ambiguous_accessions == (event.accession_number,)
