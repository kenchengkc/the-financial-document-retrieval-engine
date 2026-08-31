from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts.historical_universe_promote import (
    _identity_bounds,
    _load_current,
    _membership_verified,
)

from fdre.research.historical_component_history import HistoricalComponentRecord


def _record(
    *,
    start: date,
    end: date | None,
    added_approximate: bool = False,
    removed_approximate: bool = False,
) -> HistoricalComponentRecord:
    return HistoricalComponentRecord(
        symbol="ABC",
        cik="0000000001",
        name="Alpha Corp",
        sector="industrials",
        effective_from=start,
        effective_to=end,
        created_at=start,
        added_approximate=added_approximate,
        removed_approximate=removed_approximate,
        source_ref="a" * 40,
        source_hash="b" * 64,
    )


def test_membership_verification_requires_exact_independent_interval() -> None:
    record = _record(start=date(2012, 1, 2), end=date(2014, 5, 6))
    intervals: set[tuple[str, date, date | None]] = {
        ("ABC", date(2012, 1, 2), date(2014, 5, 6))
    }
    assert _membership_verified(record, intervals) is True
    assert _membership_verified(record, set()) is False


def test_approximate_source_dates_remain_provisional() -> None:
    record = _record(
        start=date(2012, 1, 2),
        end=date(2014, 5, 6),
        added_approximate=True,
    )
    intervals: set[tuple[str, date, date | None]] = {
        ("ABC", date(2012, 1, 2), date(2014, 5, 6))
    }
    assert _membership_verified(record, intervals) is False


def test_identity_remains_valid_on_removal_boundary_only() -> None:
    start, end = _identity_bounds(
        [_record(start=date(2012, 1, 2), end=date(2014, 5, 6))]
    )
    assert start == date(2012, 1, 2)
    assert end == date(2014, 5, 7)


def test_open_component_membership_produces_open_identity() -> None:
    start, end = _identity_bounds(
        [_record(start=date(2020, 1, 2), end=None)]
    )
    assert start == date(2020, 1, 2)
    assert end is None


def test_current_company_primary_ticker_is_deterministic_for_share_classes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "current.csv"
    path.write_text(
        "symbol,cik,name,sector\n"
        "ZZZ,0000000001,Alpha Corp,industrials\n"
        "AAA,0000000001,Alpha Corp,industrials\n",
        encoding="utf-8",
    )
    current = _load_current(path)
    assert current["0000000001"].symbol == "AAA"
