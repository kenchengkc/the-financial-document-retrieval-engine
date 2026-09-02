from __future__ import annotations

from scripts.research.historical_universe.historical_universe_blocker_queue import (
    build_remediation_queue,
)


def test_queue_prefers_exact_day_unlock_then_overlap_pressure() -> None:
    payload = {
        "blocker_audit_id": "audit",
        "input_provenance_id": "input",
        "universe_code": "sp500",
        "window_start": "2020-01-01",
        "window_end": "2020-01-10",
        "membership_blocked_day_count": 8,
        "membership_blockers": [
            {
                "blocker_id": "a",
                "security_id": 1,
                "cik": "0000000001",
                "symbols": ["AAA"],
                "effective_from": "2020-01-01",
                "effective_to": "2020-01-06",
                "source_hash": "hash-a",
                "active_day_count": 5,
                "exclusive_day_count": 3,
            },
            {
                "blocker_id": "b",
                "security_id": 2,
                "cik": "0000000002",
                "symbols": ["BBB"],
                "effective_from": "2020-01-04",
                "effective_to": "2020-01-09",
                "source_hash": "hash-b",
                "active_day_count": 5,
                "exclusive_day_count": 3,
            },
        ],
        "segments": [
            {
                "start": "2020-01-01",
                "end_exclusive": "2020-01-04",
                "day_count": 3,
                "membership_blocker_ids": ["a"],
            },
            {
                "start": "2020-01-04",
                "end_exclusive": "2020-01-06",
                "day_count": 2,
                "membership_blocker_ids": ["a", "b"],
            },
            {
                "start": "2020-01-06",
                "end_exclusive": "2020-01-09",
                "day_count": 3,
                "membership_blocker_ids": ["b"],
            },
        ],
    }

    queue = build_remediation_queue(payload)
    ranked = queue["ranked_membership_blockers"]

    # Both candidates initially unlock three days. Stable tie-breaking picks b;
    # after b is removed, resolving a unlocks the five remaining blocked days.
    assert [item["blocker_id"] for item in ranked] == ["b", "a"]
    assert [item["marginal_unlocked_day_count"] for item in ranked] == [3, 5]
    assert [item["cumulative_unlocked_day_count"] for item in ranked] == [3, 8]


def test_queue_handles_overlapping_group_with_zero_initial_marginal_unlock() -> None:
    payload = {
        "blocker_audit_id": "audit",
        "input_provenance_id": "input",
        "universe_code": "sp500",
        "window_start": "2020-01-01",
        "window_end": "2020-01-03",
        "membership_blocked_day_count": 3,
        "membership_blockers": [
            {
                "blocker_id": "a",
                "security_id": 1,
                "cik": None,
                "symbols": [],
                "effective_from": "2020-01-01",
                "effective_to": None,
                "source_hash": "hash-a",
                "active_day_count": 3,
                "exclusive_day_count": 0,
            },
            {
                "blocker_id": "b",
                "security_id": 2,
                "cik": None,
                "symbols": [],
                "effective_from": "2020-01-01",
                "effective_to": None,
                "source_hash": "hash-b",
                "active_day_count": 3,
                "exclusive_day_count": 0,
            },
        ],
        "segments": [
            {
                "start": "2020-01-01",
                "end_exclusive": "2020-01-04",
                "day_count": 3,
                "membership_blocker_ids": ["a", "b"],
            }
        ],
    }

    ranked = build_remediation_queue(payload)["ranked_membership_blockers"]
    assert ranked[0]["marginal_unlocked_day_count"] == 0
    assert ranked[1]["marginal_unlocked_day_count"] == 3
    assert ranked[1]["cumulative_unlocked_day_count"] == 3
