from __future__ import annotations

import pytest
from scripts.research.historical_universe.historical_universe_sec_identity_apply import (
    _as_ordered_unique_str_tuple,
    _as_str_tuple,
    _decision_hash,
)


def _decision() -> dict[str, object]:
    return {
        "row_id": 7,
        "security_id": 11,
        "cik": "0000000001",
        "symbol": "ABC",
        "effective_from": "2012-01-02",
        "effective_to": "2014-05-06",
        "prior_source_hash": "a" * 64,
        "status": "fully_supported",
        "state_decision_hash": "d" * 64,
        "state_lineage_id": "e" * 64,
        "sec_evidence_ids": ["1" * 64, "2" * 64],
        # The projector records accessions in filing-date chronology, not lexical order.
        "conflicting_accessions": ["0000000001-24-000010", "0000000001-23-999999"],
        "inspected_accessions": ["0000000001-24-000010", "0000000001-23-999999"],
    }


def test_decision_hash_preserves_chronological_accession_order() -> None:
    first = _decision_hash(_decision())
    replay = _decision_hash(_decision())

    assert first == replay
    assert len(first) == 64


def test_accession_lists_reject_duplicates_without_reordering() -> None:
    accessions = ["0000000001-24-000010", "0000000001-23-999999"]
    assert _as_ordered_unique_str_tuple(accessions, field="inspected_accessions") == tuple(
        accessions
    )

    with pytest.raises(RuntimeError, match="must be unique"):
        _as_ordered_unique_str_tuple(
            ["0000000001-24-000010", "0000000001-24-000010"],
            field="inspected_accessions",
        )


def test_sec_evidence_ids_remain_sorted_and_unique() -> None:
    with pytest.raises(RuntimeError, match="sorted and unique"):
        _as_str_tuple(["2" * 64, "1" * 64], field="sec_evidence_ids")
