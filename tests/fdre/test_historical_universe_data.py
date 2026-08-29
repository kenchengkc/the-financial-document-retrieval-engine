from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fdre.research.historical_universe_evidence import (
    MembershipEvidence,
    canonical_source_record_hash,
)
from fdre.research.historical_universe_identity import (
    SecCikLookupAdapter,
    SecCikNameIndex,
    StableSecurityRecord,
    resolve_issuer_name,
    resolve_membership_with_sec_issuer_fallback,
)
from fdre.research.historical_universe_pipeline import run_hu2_reconstruction
from fdre.research.historical_universe_sources import WikipediaHistoricalComponentsAdapter

OBSERVED_AT = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)


def _membership_evidence(
    *,
    source: str,
    event_type: str,
    effective_at: date,
    symbol: str = "ALP",
    name: str = "Alpha Corp",
) -> MembershipEvidence:
    return MembershipEvidence(
        universe_code="sp500",
        event_type=event_type,  # type: ignore[arg-type]
        effective_at=effective_at,
        raw_symbol=symbol,
        raw_name=name,
        source=source,
        source_url=f"https://example.test/{source}",
        source_observed_at=OBSERVED_AT,
        source_record_hash=canonical_source_record_hash(
            {
                "source": source,
                "event_type": event_type,
                "effective_at": effective_at.isoformat(),
                "symbol": symbol,
            }
        ),
    )


def test_sec_cik_lookup_parses_colon_in_company_name() -> None:
    record = SecCikLookupAdapter.parse_line(
        "11:11 CAPITAL CORP.:0001463262:\n",
        observed_at=OBSERVED_AT,
    )

    assert record is not None
    assert record.raw_name == "11:11 CAPITAL CORP."
    assert record.normalized_name == "11 11 capital corp"
    assert record.cik == "0001463262"
    assert len(record.evidence_id) == 64


def test_sec_name_resolution_fails_closed_on_multiple_ciks() -> None:
    first = SecCikLookupAdapter.parse_line("ALPHA CORP:0000000001:\n", observed_at=OBSERVED_AT)
    second = SecCikLookupAdapter.parse_line("ALPHA CORP:0000000002:\n", observed_at=OBSERVED_AT)
    assert first is not None and second is not None
    index = SecCikNameIndex((first, second))

    resolution = resolve_issuer_name("Alpha Corp.", index)

    assert resolution.status == "ambiguous"
    assert resolution.cik is None
    assert resolution.candidate_ciks == ("0000000001", "0000000002")


def test_sec_name_resolution_does_not_fuzzy_match_legal_name() -> None:
    record = SecCikLookupAdapter.parse_line(
        "ALPHA TECHNOLOGIES INC:0000000001:\n",
        observed_at=OBSERVED_AT,
    )
    assert record is not None
    index = SecCikNameIndex((record,))

    resolution = resolve_issuer_name("Alpha Technologies", index)

    assert resolution.status == "unresolved"
    assert resolution.cik is None


def test_sec_issuer_fallback_requires_unique_stable_security() -> None:
    record = SecCikLookupAdapter.parse_line("ALPHA CORP:0000000001:\n", observed_at=OBSERVED_AT)
    assert record is not None
    index = SecCikNameIndex((record,))
    evidence = _membership_evidence(
        source="source-a",
        event_type="addition",
        effective_at=date(2010, 1, 4),
    )

    resolved, issuer = resolve_membership_with_sec_issuer_fallback(
        evidence,
        identities=(),
        issuer_index=index,
        securities=(StableSecurityRecord(security_id=7, cik="0000000001"),),
    )

    assert issuer is not None and issuer.status == "resolved"
    assert resolved.status == "resolved"
    assert resolved.security_id == 7
    assert resolved.cik == "0000000001"
    assert resolved.confidence == 0.90

    ambiguous, _ = resolve_membership_with_sec_issuer_fallback(
        evidence,
        identities=(),
        issuer_index=index,
        securities=(
            StableSecurityRecord(security_id=7, cik="0000000001", share_class="A"),
            StableSecurityRecord(security_id=8, cik="0000000001", share_class="C"),
        ),
    )
    assert ambiguous.status == "ambiguous"
    assert ambiguous.candidate_security_ids == (7, 8)


def test_sec_lookup_can_filter_large_file_to_observed_names(tmp_path: Path) -> None:
    path = tmp_path / "cik-lookup-data.txt"
    path.write_text(
        "ALPHA CORP:0000000001:\n"
        "BETA CORP:0000000002:\n"
        "GAMMA CORP:0000000003:\n",
        encoding="latin-1",
    )

    records = SecCikLookupAdapter().load(
        path,
        observed_at=OBSERVED_AT,
        restrict_to_names=("Beta Corp",),
    )

    assert [record.cik for record in records] == ["0000000002"]


def test_wikipedia_adapter_parses_membership_rows_and_skips_ticker_changes(
    tmp_path: Path,
) -> None:
    html = """
    <html><body>
      <table class="wikitable">
        <tr><th>Effective Date</th><th colspan="2">Added</th><th colspan="2">Removed</th><th>Reason</th><th>Refs</th></tr>
        <tr><th></th><th>Ticker</th><th>Security</th><th>Ticker</th><th>Security</th><th></th><th></th></tr>
        <tr><td>March 20, 2020</td><td>ALP</td><td>Alpha Corp</td><td>BET</td><td>Beta Corp</td><td>Market capitalization changes.</td><td>[1]</td></tr>
        <tr><td>February 1, 2024</td><td>DAY</td><td>Dayforce</td><td>CDAY</td><td>Ceridian</td><td>Ceridian changed its ticker symbol from CDAY to DAY.</td><td>[2]</td></tr>
        <tr><td>June 30, 2026</td><td></td><td></td><td>CAG</td><td>Conagra Brands</td><td>Market capitalization changes.</td><td>[3]</td></tr>
      </table>
    </body></html>
    """
    path = tmp_path / "historical.html"
    path.write_text(html, encoding="utf-8")

    records = WikipediaHistoricalComponentsAdapter().load(path, observed_at=OBSERVED_AT)

    assert [(item.event_type, item.raw_symbol) for item in records] == [
        ("addition", "ALP"),
        ("removal", "BET"),
        ("removal", "CAG"),
    ]
    assert all(item.source == "wikipedia-sp500-historical-components" for item in records)
    assert all(item.announced_at is None for item in records)
    assert dict(records[0].metadata)["reason"] == "Market capitalization changes."


def test_two_real_source_shapes_can_verify_and_materialize_via_sec_issuer_identity() -> None:
    sec_record = SecCikLookupAdapter.parse_line(
        "ALPHA CORP:0000000001:\n",
        observed_at=OBSERVED_AT,
    )
    assert sec_record is not None
    issuer_index = SecCikNameIndex((sec_record,))
    securities = (StableSecurityRecord(security_id=11, cik="0000000001"),)

    evidence = (
        _membership_evidence(
            source="shawnlinxl/snp-history",
            event_type="addition",
            effective_at=date(2010, 1, 4),
        ),
        _membership_evidence(
            source="wikipedia-sp500-historical-components",
            event_type="addition",
            effective_at=date(2010, 1, 4),
        ),
        _membership_evidence(
            source="shawnlinxl/snp-history",
            event_type="removal",
            effective_at=date(2015, 6, 1),
        ),
        _membership_evidence(
            source="wikipedia-sp500-historical-components",
            event_type="removal",
            effective_at=date(2015, 6, 1),
        ),
    )

    result = run_hu2_reconstruction(
        evidence,
        identities=(),
        issuer_index=issuer_index,
        securities=securities,
    )

    assert len(result.events) == 2
    assert all(event.verification_status == "verified" for event in result.events)
    assert len(result.memberships) == 1
    membership = result.memberships[0]
    assert membership.security_id == 11
    assert membership.effective_from == date(2010, 1, 4)
    assert membership.effective_to == date(2015, 6, 1)
    assert membership.verification_status == "verified"
    assert result.audit.source_count == 2
    assert result.audit.verified_event_count == 2
    assert result.audit.materialized_interval_count == 1
    assert result.audit.verified_interval_count == 1
    assert dict(result.audit.issuer_resolution_counts) == {"resolved": 4}
    assert dict(result.audit.security_resolution_counts) == {"resolved": 4}
    assert len(result.audit.audit_id) == 64


def test_hu2_audit_is_deterministic_under_input_order() -> None:
    sec_record = SecCikLookupAdapter.parse_line(
        "ALPHA CORP:0000000001:\n",
        observed_at=OBSERVED_AT,
    )
    assert sec_record is not None
    issuer_index = SecCikNameIndex((sec_record,))
    securities = (StableSecurityRecord(security_id=11, cik="0000000001"),)
    first = _membership_evidence(
        source="source-a",
        event_type="addition",
        effective_at=date(2010, 1, 4),
    )
    second = _membership_evidence(
        source="source-b",
        event_type="addition",
        effective_at=date(2010, 1, 4),
    )

    left = run_hu2_reconstruction(
        (first, second), identities=(), issuer_index=issuer_index, securities=securities
    )
    right = run_hu2_reconstruction(
        (second, first), identities=(), issuer_index=issuer_index, securities=securities
    )

    assert left.audit.audit_id == right.audit.audit_id
    assert left.events == right.events
