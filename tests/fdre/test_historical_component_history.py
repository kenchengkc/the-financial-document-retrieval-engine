from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fdre.research.historical_component_history import (
    HistoricalComponentHistoryAdapter,
    HistoricalComponentIdentityIndex,
    resolve_component_identity,
)
from fdre.research.historical_universe_evidence import (
    MembershipEvidence,
    canonical_source_record_hash,
)

OBSERVED_AT = datetime(2026, 8, 30, 17, 0, tzinfo=UTC)


def _evidence(*, symbol: str, when: date, event_type: str = "addition") -> MembershipEvidence:
    return MembershipEvidence(
        universe_code="sp500",
        event_type=event_type,  # type: ignore[arg-type]
        effective_at=when,
        raw_symbol=symbol,
        raw_name="Source Name Variant",
        source="source-a",
        source_observed_at=OBSERVED_AT,
        source_record_hash=canonical_source_record_hash(
            {"symbol": symbol, "when": when.isoformat(), "event_type": event_type}
        ),
    )


def _history(tmp_path: Path, rows: str) -> HistoricalComponentIdentityIndex:
    path = tmp_path / "components_history.csv"
    path.write_text(
        "symbol,cik,name,sector,date_added,date_removed,created_at\n" + rows,
        encoding="utf-8",
    )
    records = HistoricalComponentHistoryAdapter(source_ref="a" * 40).load(path)
    return HistoricalComponentIdentityIndex(records)


def test_unique_historical_symbol_resolves_without_name_similarity(tmp_path: Path) -> None:
    index = _history(
        tmp_path,
        (
            "AAP,0001158449,Advance Auto Parts,consumer_discretionary,"
            "2015-07-09,2023-08-25,2015-07-09\n"
        ),
    )
    resolution = resolve_component_identity(
        _evidence(symbol="AAP", when=date(2015, 7, 8)),
        index,
    )
    assert resolution.status == "resolved"
    assert resolution.method == "unique_symbol_history"
    assert resolution.cik == "0001158449"


def test_reused_symbol_requires_dated_unique_cik(tmp_path: Path) -> None:
    index = _history(
        tmp_path,
        "XYZ,0000000001,Old Co,industrials,2010-01-01,2015-01-01,2010-01-01\n"
        "XYZ,0000000002,New Co,industrials,2015-01-01,,2015-01-01\n",
    )
    old = resolve_component_identity(
        _evidence(symbol="XYZ", when=date(2014, 6, 1)), index
    )
    new = resolve_component_identity(
        _evidence(symbol="XYZ", when=date(2016, 6, 1)), index
    )
    assert old.status == "resolved" and old.cik == "0000000001"
    assert old.method == "dated_symbol_history"
    assert new.status == "resolved" and new.cik == "0000000002"


def test_reused_symbol_fails_closed_when_date_does_not_disambiguate(tmp_path: Path) -> None:
    index = _history(
        tmp_path,
        "XYZ,0000000001,Old Co,industrials,2010-01-01,2016-01-01,2010-01-01\n"
        "XYZ,0000000002,New Co,industrials,2015-01-01,,2015-01-01\n",
    )
    resolution = resolve_component_identity(
        _evidence(symbol="XYZ", when=date(2015, 6, 1)), index
    )
    assert resolution.status == "ambiguous"
    assert resolution.cik is None
    assert resolution.candidate_ciks == ("0000000001", "0000000002")


def test_starred_source_dates_are_preserved_as_approximate(tmp_path: Path) -> None:
    path = tmp_path / "components_history.csv"
    path.write_text(
        "symbol,cik,name,sector,date_added,date_removed,created_at\n"
        "ABC,0000000001,Alpha Corp,industrials,2010-01-01*,2012-01-01*,2010-01-02\n",
        encoding="utf-8",
    )
    record = HistoricalComponentHistoryAdapter(source_ref="b" * 40).load(path)[0]
    assert record.effective_from == date(2010, 1, 1)
    assert record.effective_to == date(2012, 1, 1)
    assert record.added_approximate is True
    assert record.removed_approximate is True
    assert record.source_valid_from == date(2010, 1, 2)


def test_source_validity_never_backdates_a_later_symbol_observation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "components_history.csv"
    path.write_text(
        "symbol,cik,name,sector,date_added,date_removed,created_at\n"
        "NEW,0000000001,Renamed Corp,industrials,2000-01-01,,2015-06-01\n",
        encoding="utf-8",
    )
    record = HistoricalComponentHistoryAdapter(source_ref="c" * 40).load(path)[0]

    assert record.effective_from == date(2000, 1, 1)
    assert record.source_valid_from == date(2015, 6, 1)


def test_trailing_table_delimiter_is_syntax_cleanup_only(tmp_path: Path) -> None:
    index = _history(
        tmp_path,
        "ALLE,0001579241,Allegion,industrials,2013-12-02,,2013-12-01\n",
    )
    resolution = resolve_component_identity(
        _evidence(symbol="ALLE |", when=date(2013, 12, 2)), index
    )
    assert resolution.status == "resolved"
    assert resolution.cik == "0001579241"


def test_exact_upstream_xom_holding_company_cik_is_corrected(tmp_path: Path) -> None:
    index = _history(
        tmp_path,
        "XOM,0002115436,ExxonMobil,energy,1957-03-04,,2007-03-05\n",
    )
    resolution = resolve_component_identity(
        _evidence(symbol="XOM", when=date(2020, 1, 2)), index
    )

    assert resolution.status == "resolved"
    assert resolution.cik == "0000034088"
