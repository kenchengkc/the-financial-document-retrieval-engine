from datetime import date

from fdre.research.historical_universe_evidence import ReconciledMembershipEvent
from fdre.research.historical_universe_materialization import materialize_membership_intervals


def _event(
    event_type: str,
    effective_at: date,
    *,
    status: str = "verified",
    security_id: int = 1,
    conflict_codes: tuple[str, ...] = (),
    suffix: str = "a",
) -> ReconciledMembershipEvent:
    return ReconciledMembershipEvent(
        universe_code="sp500",
        event_type=event_type,  # type: ignore[arg-type]
        security_id=security_id,
        cik=f"000000000{security_id}",
        effective_at=effective_at,
        announced_at=None,
        effective_session="after_close",
        evidence_ids=(f"evidence-{suffix}",),
        distinct_sources=2 if status == "verified" else 1,
        verification_status=status,  # type: ignore[arg-type]
        confidence=0.95 if status == "verified" else 0.75,
        conflict_codes=conflict_codes,
        reconciliation_hash=(suffix * 64)[:64],
    )


def test_addition_then_removal_materializes_bounded_interval() -> None:
    result = materialize_membership_intervals(
        [
            _event("addition", date(2020, 1, 1), suffix="a"),
            _event("removal", date(2021, 1, 1), suffix="b"),
        ]
    )

    assert len(result.memberships) == 1
    membership = result.memberships[0]
    assert membership.effective_from == date(2020, 1, 1)
    assert membership.effective_to == date(2021, 1, 1)
    assert membership.verification_status == "verified"
    assert membership.confidence == 0.95
    assert result.issues == ()
    assert len(result.materialization_id) == 64


def test_orphan_removal_does_not_infer_unknown_start() -> None:
    result = materialize_membership_intervals(
        [_event("removal", date(2020, 1, 1), suffix="a")]
    )

    assert result.memberships == ()
    assert [issue.code for issue in result.issues] == ["orphan_removal"]


def test_open_addition_does_not_infer_unknown_end() -> None:
    result = materialize_membership_intervals(
        [_event("addition", date(2020, 1, 1), suffix="a")]
    )

    assert result.memberships == ()
    assert [issue.code for issue in result.issues] == ["open_membership_unbounded"]


def test_duplicate_addition_is_reported_and_original_start_is_preserved() -> None:
    result = materialize_membership_intervals(
        [
            _event("addition", date(2020, 1, 1), suffix="a"),
            _event("addition", date(2020, 6, 1), suffix="b"),
            _event("removal", date(2021, 1, 1), suffix="c"),
        ]
    )

    assert len(result.memberships) == 1
    assert result.memberships[0].effective_from == date(2020, 1, 1)
    assert result.memberships[0].effective_to == date(2021, 1, 1)
    assert [issue.code for issue in result.issues] == ["duplicate_addition"]


def test_provisional_boundary_makes_interval_provisional() -> None:
    result = materialize_membership_intervals(
        [
            _event("addition", date(2020, 1, 1), status="verified", suffix="a"),
            _event("removal", date(2021, 1, 1), status="provisional", suffix="b"),
        ]
    )

    assert result.memberships[0].verification_status == "provisional"
    assert result.memberships[0].confidence == 0.75


def test_same_date_add_remove_conflict_is_not_materialized() -> None:
    result = materialize_membership_intervals(
        [
            _event(
                "addition",
                date(2020, 1, 1),
                status="provisional",
                conflict_codes=("opposite_event_same_date",),
                suffix="a",
            ),
            _event(
                "removal",
                date(2020, 1, 1),
                status="provisional",
                conflict_codes=("opposite_event_same_date",),
                suffix="b",
            ),
        ]
    )

    assert result.memberships == ()
    assert [issue.code for issue in result.issues] == ["conflicting_events"]


def test_materialization_is_order_independent() -> None:
    events = [
        _event("addition", date(2020, 1, 1), suffix="a"),
        _event("removal", date(2021, 1, 1), suffix="b"),
    ]

    first = materialize_membership_intervals(events)
    second = materialize_membership_intervals(list(reversed(events)))

    assert first.materialization_id == second.materialization_id
    assert first.memberships == second.memberships
