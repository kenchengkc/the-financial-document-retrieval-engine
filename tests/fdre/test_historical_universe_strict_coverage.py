from __future__ import annotations

from datetime import date

import pytest

from fdre.research.historical_universe_strict_coverage import (
    ProvisionalMembershipBlocker,
    build_strict_coverage_audit,
)


def _blocker(
    membership_id: int,
    start: date,
    end: date | None,
) -> ProvisionalMembershipBlocker:
    return ProvisionalMembershipBlocker(
        membership_id=membership_id,
        security_id=100 + membership_id,
        cik=f"{membership_id:010d}",
        effective_from=start,
        effective_to=end,
        source="test-source",
        source_url=None,
        source_hash=f"{membership_id:064x}",
        confidence=0.85,
    )


def test_audit_measures_union_without_double_counting_overlaps() -> None:
    audit = build_strict_coverage_audit(
        (
            _blocker(1, date(2020, 1, 2), date(2020, 1, 6)),
            _blocker(2, date(2020, 1, 4), date(2020, 1, 8)),
        ),
        universe_code="sp500",
        window_start=date(2020, 1, 1),
        window_end=date(2020, 1, 8),
    )

    assert audit.day_count == 8
    assert audit.blocked_day_count == 6
    assert audit.strict_eligible_day_count == 2
    assert audit.blocked_days_by_membership == ((1, 4), (2, 4))
    assert audit.unique_blocked_days_by_membership == ((1, 2), (2, 2))


def test_open_interval_is_clipped_to_research_window() -> None:
    audit = build_strict_coverage_audit(
        (_blocker(9, date(2019, 1, 1), None),),
        universe_code="SP500",
        window_start=date(2020, 1, 1),
        window_end=date(2020, 1, 3),
    )

    assert audit.universe_code == "sp500"
    assert audit.blocked_day_count == 3
    assert audit.strict_eligible_day_count == 0
    assert audit.segments[0].blocker_ids == (9,)


def test_greedy_cover_ranks_newly_unblocked_days_deterministically() -> None:
    audit = build_strict_coverage_audit(
        (
            _blocker(1, date(2020, 1, 1), date(2020, 1, 7)),
            _blocker(2, date(2020, 1, 3), date(2020, 1, 5)),
            _blocker(3, date(2020, 1, 7), date(2020, 1, 10)),
        ),
        universe_code="sp500",
        window_start=date(2020, 1, 1),
        window_end=date(2020, 1, 9),
    )

    assert [item.membership_id for item in audit.greedy_cover] == [1, 3]
    assert [item.newly_covered_days for item in audit.greedy_cover] == [6, 3]
    assert audit.greedy_cover[-1].remaining_blocked_days == 0


def test_audit_identity_is_replay_deterministic() -> None:
    blockers = (
        _blocker(2, date(2020, 1, 3), None),
        _blocker(1, date(2020, 1, 1), date(2020, 1, 7)),
    )
    first = build_strict_coverage_audit(
        blockers,
        universe_code="sp500",
        window_start=date(2020, 1, 1),
        window_end=date(2020, 1, 9),
    )
    replay = build_strict_coverage_audit(
        tuple(reversed(blockers)),
        universe_code="sp500",
        window_start=date(2020, 1, 1),
        window_end=date(2020, 1, 9),
    )

    assert first.audit_id == replay.audit_id


def test_duplicate_membership_ids_fail_closed() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        build_strict_coverage_audit(
            (
                _blocker(1, date(2020, 1, 1), None),
                _blocker(1, date(2020, 1, 2), None),
            ),
            universe_code="sp500",
            window_start=date(2020, 1, 1),
            window_end=date(2020, 1, 9),
        )
