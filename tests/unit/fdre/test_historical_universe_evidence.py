from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fdre.research.historical_universe import SecurityIdentityRecord
from fdre.research.historical_universe_evidence import (
    IdentityResolution,
    MembershipEvidence,
    SnpHistoryCsvAdapter,
    canonical_source_record_hash,
    reconcile_membership_evidence,
    resolve_membership_evidence,
)

OBSERVED_AT = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)


def _evidence(
    *,
    source: str,
    event_type: str = "addition",
    symbol: str = "ABC",
    effective_at: date = date(2020, 3, 20),
    raw_cik: str | None = None,
) -> MembershipEvidence:
    return MembershipEvidence(
        universe_code="sp500",
        event_type=event_type,  # type: ignore[arg-type]
        effective_at=effective_at,
        announced_at=date(2020, 3, 15),
        effective_session="after_close",
        raw_symbol=symbol,
        raw_name="ABC Corp",
        raw_cik=raw_cik,
        source=source,
        source_url=f"https://example.test/{source}",
        source_observed_at=OBSERVED_AT,
        source_record_id="1",
        source_record_hash=canonical_source_record_hash(
            {"source": source, "event_type": event_type, "symbol": symbol}
        ),
    )


def _identity(
    security_id: int,
    symbol: str,
    *,
    cik: str,
    name: str = "ABC Corp",
    start: date = date(2010, 1, 1),
    end: date | None = None,
) -> SecurityIdentityRecord:
    return SecurityIdentityRecord(
        security_id=security_id,
        cik=cik,
        symbol=symbol,
        name=name,
        exchange="NYSE",
        effective_from=start,
        effective_to=end,
        source_hash=f"identity-{security_id}".ljust(64, "0")[:64],
    )


def test_source_record_hash_is_mapping_order_independent() -> None:
    first = canonical_source_record_hash({"ticker": "ABC", "date": "2020-03-20"})
    second = canonical_source_record_hash({"date": "2020-03-20", "ticker": "ABC"})

    assert first == second
    assert len(first) == 64


def test_snp_history_adapter_splits_addition_and_removal(tmp_path: Path) -> None:
    source = tmp_path / "history.csv"
    source.write_text(
        "Announced,Implemented,,Addition,Addition Ticker,Removal,Removal Ticker,"
        "Removal Type,Reason for Removal\n"
        "3/15/2020,3/20/2020,After Close,Alpha Corp,ALP,Beta Corp,BET,M&A,Acquired\n",
        encoding="utf-8",
    )

    records = SnpHistoryCsvAdapter().load(source, observed_at=OBSERVED_AT)

    assert len(records) == 2
    addition, removal = records
    assert addition.event_type == "addition"
    assert addition.raw_symbol == "ALP"
    assert addition.effective_at == date(2020, 3, 20)
    assert addition.effective_session == "after_close"
    assert removal.event_type == "removal"
    assert removal.raw_symbol == "BET"
    assert dict(removal.metadata) == {
        "removal_type": "M&A",
        "removal_reason": "Acquired",
    }
    assert addition.source_record_hash == removal.source_record_hash
    assert addition.evidence_id != removal.evidence_id


def test_snp_history_adapter_rejects_incomplete_schema(tmp_path: Path) -> None:
    source = tmp_path / "history.csv"
    source.write_text("Implemented,Addition Ticker\n3/20/2020,ABC\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required snp-history columns"):
        SnpHistoryCsvAdapter().load(source, observed_at=OBSERVED_AT)


def test_snp_history_adapter_skips_absent_na_side_without_inventing_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "history.csv"
    source.write_text(
        "Announced,Implemented,,Addition,Addition Ticker,Removal,Removal Ticker,"
        "Removal Type,Reason for Removal\n"
        "3/11/2014,4/3/2014,After Close,Google Inc. Class C,GOOGL,N/A,,N/A,N/A\n"
        "4/1/2014,4/7/2014,After Close,N/A,N/A,Beta Corp,BET,Failure,N/A\n",
        encoding="utf-8",
    )

    records = SnpHistoryCsvAdapter().load(source, observed_at=OBSERVED_AT)

    assert [(record.event_type, record.raw_symbol) for record in records] == [
        ("addition", "GOOGL"),
        ("removal", "BET"),
    ]
    assert dict(records[1].metadata) == {"removal_type": "Failure"}


def test_resolution_prefers_exact_historical_identity_without_future_inference() -> None:
    evidence = _evidence(source="source-a", symbol="BRK.B")
    identities = [
        _identity(1, "BRK-B", cik="0001067983", name="Berkshire Hathaway Inc"),
        _identity(
            2,
            "ABC",
            cik="0000000002",
            start=date(2022, 1, 1),
        ),
    ]

    resolution = resolve_membership_evidence(evidence, identities)

    assert resolution.status == "resolved"
    assert resolution.security_id == 1
    assert resolution.cik == "0001067983"
    assert resolution.method == "symbol_exact"
    assert resolution.confidence == 0.95


def test_cik_symbol_conflict_is_ambiguous_not_silently_overridden() -> None:
    evidence = _evidence(
        source="source-a",
        symbol="AAA",
        raw_cik="2",
    )
    identities = [
        _identity(1, "AAA", cik="0000000001"),
        _identity(2, "BBB", cik="0000000002"),
    ]

    resolution = resolve_membership_evidence(evidence, identities)

    assert resolution.status == "ambiguous"
    assert resolution.security_id is None
    assert resolution.candidate_security_ids == (1, 2)
    assert resolution.reason is not None
    assert "different securities" in resolution.reason


def test_unmatched_identity_remains_unresolved() -> None:
    evidence = _evidence(source="source-a", symbol="OLD")
    identities = [
        _identity(
            1,
            "OLD",
            cik="0000000001",
            start=date(2010, 1, 1),
            end=date(2019, 1, 1),
        )
    ]

    resolution = resolve_membership_evidence(evidence, identities)

    assert resolution.status == "unresolved"
    assert resolution.security_id is None


def test_two_independent_sources_can_verify_same_resolved_event() -> None:
    first = _evidence(source="source-a")
    second = _evidence(source="source-b")
    resolutions = [
        IdentityResolution(
            evidence_id=first.evidence_id,
            status="resolved",
            method="symbol_exact",
            confidence=0.95,
            security_id=1,
            cik="0000000001",
            candidate_security_ids=(1,),
        ),
        IdentityResolution(
            evidence_id=second.evidence_id,
            status="resolved",
            method="symbol_exact",
            confidence=0.95,
            security_id=1,
            cik="0000000001",
            candidate_security_ids=(1,),
        ),
    ]

    result = reconcile_membership_evidence([first, second], resolutions)

    assert len(result.events) == 1
    event = result.events[0]
    assert event.verification_status == "verified"
    assert event.distinct_sources == 2
    assert event.conflict_codes == ()
    assert result.audit.verified_event_count == 1
    assert result.audit.resolved_count == 2
    assert result.audit.source_count == 2


def test_single_source_stays_provisional() -> None:
    record = _evidence(source="source-a")
    resolution = IdentityResolution(
        evidence_id=record.evidence_id,
        status="resolved",
        method="symbol_exact",
        confidence=0.95,
        security_id=1,
        cik="0000000001",
        candidate_security_ids=(1,),
    )

    result = reconcile_membership_evidence([record], [resolution])

    assert result.events[0].verification_status == "provisional"
    assert result.events[0].confidence == 0.76
    assert result.audit.provisional_event_count == 1


def test_opposite_events_same_security_and_date_fail_to_provisional() -> None:
    addition = _evidence(source="source-a", event_type="addition")
    removal = _evidence(source="source-b", event_type="removal")
    resolutions = [
        IdentityResolution(
            evidence_id=record.evidence_id,
            status="resolved",
            method="symbol_exact",
            confidence=0.95,
            security_id=1,
            cik="0000000001",
            candidate_security_ids=(1,),
        )
        for record in (addition, removal)
    ]

    result = reconcile_membership_evidence([addition, removal], resolutions)

    assert len(result.events) == 2
    assert all(event.verification_status == "provisional" for event in result.events)
    assert all("opposite_event_same_date" in event.conflict_codes for event in result.events)
    assert result.audit.conflict_event_count == 2


def test_audit_tracks_ambiguous_and_unresolved_evidence() -> None:
    resolved = _evidence(source="source-a", symbol="AAA")
    ambiguous = _evidence(source="source-b", symbol="BBB")
    unresolved = _evidence(source="source-c", symbol="CCC")
    resolutions = [
        IdentityResolution(
            evidence_id=resolved.evidence_id,
            status="resolved",
            method="symbol_exact",
            confidence=0.95,
            security_id=1,
            cik="0000000001",
            candidate_security_ids=(1,),
        ),
        IdentityResolution(
            evidence_id=ambiguous.evidence_id,
            status="ambiguous",
            method="symbol_exact",
            confidence=0.0,
            candidate_security_ids=(2, 3),
            reason="multiple candidates",
        ),
        IdentityResolution(
            evidence_id=unresolved.evidence_id,
            status="unresolved",
            method="unresolved",
            confidence=0.0,
            reason="no candidate",
        ),
    ]

    result = reconcile_membership_evidence([resolved, ambiguous, unresolved], resolutions)

    assert result.audit.evidence_count == 3
    assert result.audit.resolved_count == 1
    assert result.audit.ambiguous_count == 1
    assert result.audit.unresolved_count == 1
    assert result.audit.coverage_start == date(2020, 3, 20)
    assert result.audit.coverage_end == date(2020, 3, 20)
    assert len(result.audit.audit_id) == 64
