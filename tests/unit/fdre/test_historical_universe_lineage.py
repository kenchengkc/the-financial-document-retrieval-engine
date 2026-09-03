from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fdre.research.historical_universe import SecurityIdentityRecord
from fdre.research.historical_universe_evidence import (
    MembershipEventType,
    MembershipEvidence,
    canonical_source_record_hash,
)
from fdre.research.historical_universe_identity import SecCikLookupAdapter, SecCikNameIndex
from fdre.research.historical_universe_lineage import (
    TickerMembershipLineageAdapter,
    resolve_evidence_via_ticker_lineage,
)

OBSERVED_AT = datetime(2026, 8, 30, 16, 0, tzinfo=UTC)


def _evidence(
    *,
    source: str,
    event_type: MembershipEventType,
    effective_at: date,
    symbol: str = "ABC",
    name: str = "Alpha Corp",
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
        source_observed_at=OBSERVED_AT,
        source_record_hash=canonical_source_record_hash(payload),
    )


def _lineage_file(tmp_path: Path) -> Path:
    path = tmp_path / "ticker-intervals.csv"
    path.write_text(
        "ticker,start_date,end_date\n"
        "ABC,2010-01-04,2015-06-01\n"
        "ABC,2020-01-02,\n"
        "XYZ,2012-03-01,2017-04-03\n",
        encoding="utf-8",
    )
    return path


def _sec_index() -> SecCikNameIndex:
    row = SecCikLookupAdapter.parse_line(
        "ALPHA CORP:0000000007:\n",
        observed_at=OBSERVED_AT,
    )
    assert row is not None
    return SecCikNameIndex((row,))


def test_exact_addition_and_removal_boundaries_share_one_lineage(tmp_path: Path) -> None:
    lineages = TickerMembershipLineageAdapter(source_ref="abc123").load(
        _lineage_file(tmp_path)
    )
    evidence = (
        _evidence(
            source="source-a",
            event_type="addition",
            effective_at=date(2010, 1, 4),
        ),
        _evidence(
            source="source-b",
            event_type="removal",
            effective_at=date(2015, 6, 1),
            name="Alpha Incorporated",
        ),
    )

    resolutions = resolve_evidence_via_ticker_lineage(
        evidence,
        lineages=lineages,
        sec_index=_sec_index(),
    )

    assert [row.status for row in resolutions] == ["resolved", "resolved"]
    assert {row.cik for row in resolutions} == {"0000000007"}
    assert len({row.lineage_id for row in resolutions}) == 1


def test_lineage_never_propagates_between_reused_ticker_intervals(tmp_path: Path) -> None:
    lineages = TickerMembershipLineageAdapter(source_ref="abc123").load(
        _lineage_file(tmp_path)
    )
    evidence = (
        _evidence(
            source="source-a",
            event_type="addition",
            effective_at=date(2010, 1, 4),
        ),
        _evidence(
            source="source-b",
            event_type="addition",
            effective_at=date(2020, 1, 2),
            name="Unknown Reuser",
        ),
    )

    resolutions = resolve_evidence_via_ticker_lineage(
        evidence,
        lineages=lineages,
        sec_index=_sec_index(),
    )

    by_id = {row.evidence_id: row for row in resolutions}
    assert by_id[evidence[0].evidence_id].status == "resolved"
    reused = by_id[evidence[1].evidence_id]
    assert reused.status == "unresolved"
    assert reused.cik is None
    assert reused.reason == "ticker interval has no issuer CIK support"


def test_open_interval_can_be_supported_by_exact_current_identity(tmp_path: Path) -> None:
    lineages = TickerMembershipLineageAdapter(source_ref="abc123").load(
        _lineage_file(tmp_path)
    )
    evidence = (
        _evidence(
            source="source-a",
            event_type="addition",
            effective_at=date(2020, 1, 2),
            name="Name Not In SEC Index",
        ),
    )
    current_identity = SecurityIdentityRecord(
        security_id=11,
        cik="0000000099",
        symbol="ABC",
        name="Current ABC",
        exchange="NYSE",
        effective_from=date(2026, 6, 8),
        effective_to=None,
        source_hash="f" * 64,
        verification_status="provisional",
        confidence=0.9,
    )

    resolutions = resolve_evidence_via_ticker_lineage(
        evidence,
        lineages=lineages,
        sec_index=SecCikNameIndex(()),
        current_identities=(current_identity,),
    )

    assert resolutions[0].status == "resolved"
    assert resolutions[0].cik == "0000000099"
    assert "fdre-current-security-identity" in resolutions[0].supporting_sources


def test_non_boundary_event_does_not_inherit_interval_identity(tmp_path: Path) -> None:
    lineages = TickerMembershipLineageAdapter(source_ref="abc123").load(
        _lineage_file(tmp_path)
    )
    evidence = (
        _evidence(
            source="source-a",
            event_type="addition",
            effective_at=date(2011, 1, 4),
        ),
    )

    resolution = resolve_evidence_via_ticker_lineage(
        evidence,
        lineages=lineages,
        sec_index=_sec_index(),
    )[0]

    assert resolution.status == "unresolved"
    assert resolution.lineage_id is None
    assert resolution.reason == "no exact complete-history ticker interval boundary match"
