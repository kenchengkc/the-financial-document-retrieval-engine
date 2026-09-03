from __future__ import annotations

from datetime import UTC, date, datetime

from scripts.research.historical_universe.historical_security_seed_plan import (
    build_historical_security_seed_plan,
)

from fdre.research.historical_universe_evidence import (
    MembershipEventType,
    MembershipEvidence,
    canonical_source_record_hash,
)
from fdre.research.historical_universe_identity import (
    SecCikLookupAdapter,
    SecCikNameIndex,
    StableSecurityRecord,
)

OBSERVED_AT = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _evidence(
    *,
    source: str,
    event_type: MembershipEventType = "addition",
    effective_at: date = date(2012, 1, 3),
    symbol: str = "OLD",
    name: str = "Old Corp",
) -> MembershipEvidence:
    payload = {
        "source": source,
        "event_type": event_type,
        "effective_at": effective_at.isoformat(),
        "symbol": symbol,
        "name": name,
    }
    return MembershipEvidence(
        universe_code="sp500",
        event_type=event_type,
        effective_at=effective_at,
        raw_symbol=symbol,
        raw_name=name,
        source=source,
        source_url=f"https://example.test/{source}",
        source_observed_at=OBSERVED_AT,
        source_record_hash=canonical_source_record_hash(payload),
    )


def _sec_index() -> SecCikNameIndex:
    row = SecCikLookupAdapter.parse_line(
        "OLD CORP:0000000007:\n",
        observed_at=OBSERVED_AT,
    )
    assert row is not None
    return SecCikNameIndex((row,))


def test_planner_selects_one_symbol_two_source_historical_issuer() -> None:
    evidence = (
        _evidence(source="source-a"),
        _evidence(source="source-b"),
    )

    report = build_historical_security_seed_plan(
        evidence,
        sec_index=_sec_index(),
        existing_company_ciks=set(),
        stable_securities=(),
    )

    assert report["candidate_cik_count"] == 1
    assert report["candidate_target_evidence_count"] == 2
    assert report["candidate_missing_company_count"] == 1
    candidates = report["candidates"]
    assert isinstance(candidates, list)
    candidate = candidates[0]
    assert candidate["cik"] == "0000000007"
    assert candidate["symbol"] == "OLD"
    assert candidate["company_row_exists"] is False
    assert candidate["requires_historical_company_row"] is True
    assert candidate["target_exact_two_source_event_count"] == 1
    assert report["write_performed"] is False


def test_planner_excludes_cik_with_multiple_observed_symbols() -> None:
    evidence = (
        _evidence(source="source-a", symbol="OLD"),
        _evidence(source="source-b", symbol="OLD"),
        _evidence(
            source="source-a",
            effective_at=date(2014, 2, 3),
            symbol="NEW",
        ),
        _evidence(
            source="source-b",
            effective_at=date(2014, 2, 3),
            symbol="NEW",
        ),
    )

    report = build_historical_security_seed_plan(
        evidence,
        sec_index=_sec_index(),
        existing_company_ciks=set(),
        stable_securities=(),
    )

    assert report["candidate_cik_count"] == 0
    assert report["exclusion_cik_counts"] == {"multiple_observed_symbols": 1}


def test_planner_excludes_opposing_same_symbol_boundary() -> None:
    evidence = (
        _evidence(source="source-a", event_type="addition"),
        _evidence(source="source-b", event_type="addition"),
        _evidence(source="source-a", event_type="removal"),
    )

    report = build_historical_security_seed_plan(
        evidence,
        sec_index=_sec_index(),
        existing_company_ciks=set(),
        stable_securities=(),
    )

    assert report["candidate_cik_count"] == 0
    exclusions = report["exclusion_cik_counts"]
    assert isinstance(exclusions, dict)
    assert exclusions["opposing_same_symbol_target_event"] == 1


def test_planner_excludes_existing_stable_common_stock_security() -> None:
    evidence = (
        _evidence(source="source-a"),
        _evidence(source="source-b"),
    )

    report = build_historical_security_seed_plan(
        evidence,
        sec_index=_sec_index(),
        existing_company_ciks={"0000000007"},
        stable_securities=(StableSecurityRecord(security_id=11, cik="0000000007"),),
    )

    assert report["candidate_cik_count"] == 0
    assert report["exclusion_cik_counts"] == {"existing_stable_common_stock_security": 1}
