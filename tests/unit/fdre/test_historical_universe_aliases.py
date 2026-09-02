from __future__ import annotations

from datetime import UTC, date, datetime

from fdre.research.historical_universe_evidence import (
    MembershipEvidence,
    canonical_source_record_hash,
)
from fdre.research.historical_universe_identity import (
    SecCikLookupAdapter,
    SecCikNameIndex,
    StableSecurityRecord,
    derive_cross_source_issuer_aliases,
)
from fdre.research.historical_universe_pipeline import run_hu2_reconstruction

OBSERVED_AT = datetime(2026, 8, 30, tzinfo=UTC)


def _evidence(*, source: str, when: date, name: str, symbol: str = "ALP") -> MembershipEvidence:
    return MembershipEvidence(
        universe_code="sp500",
        event_type="addition",
        effective_at=when,
        raw_symbol=symbol,
        raw_name=name,
        source=source,
        source_observed_at=OBSERVED_AT,
        source_record_hash=canonical_source_record_hash(
            {"source": source, "when": when.isoformat(), "name": name, "symbol": symbol}
        ),
    )


def test_derived_alias_is_scoped_to_the_supported_evidence_row() -> None:
    sec = SecCikLookupAdapter.parse_line(
        "ALPHA CORPORATION:0000000001:\n",
        observed_at=OBSERVED_AT,
    )
    assert sec is not None
    sec_index = SecCikNameIndex((sec,))
    supported_date = date(2012, 6, 1)
    exact = _evidence(source="source-a", when=supported_date, name="Alpha Corporation")
    supported_alias = _evidence(source="source-b", when=supported_date, name="Alpha Corp")
    unsupported_reuse = _evidence(
        source="source-c",
        when=date(2013, 6, 1),
        name="Alpha Corp",
    )

    result = run_hu2_reconstruction(
        (unsupported_reuse, supported_alias, exact),
        identities=(),
        issuer_index=sec_index,
        securities=(StableSecurityRecord(security_id=11, cik="0000000001"),),
    )
    resolutions = {
        record.evidence_id: resolution
        for record, resolution in zip(
            sorted((unsupported_reuse, supported_alias, exact), key=lambda item: item.evidence_id),
            result.resolutions,
            strict=True,
        )
    }

    assert resolutions[exact.evidence_id].status == "resolved"
    assert resolutions[supported_alias.evidence_id].status == "resolved"
    assert resolutions[supported_alias.evidence_id].confidence == 0.85
    assert resolutions[unsupported_reuse.evidence_id].status == "unresolved"


def test_conflicting_cross_event_alias_ciks_are_discarded() -> None:
    alpha = SecCikLookupAdapter.parse_line(
        "ALPHA CORPORATION:0000000001:\n",
        observed_at=OBSERVED_AT,
    )
    other = SecCikLookupAdapter.parse_line(
        "OTHER CORPORATION:0000000002:\n",
        observed_at=OBSERVED_AT,
    )
    assert alpha is not None and other is not None
    sec_index = SecCikNameIndex((alpha, other))
    evidence = (
        _evidence(source="source-a", when=date(2012, 6, 1), name="Alpha Corporation"),
        _evidence(source="source-b", when=date(2012, 6, 1), name="Shared Alias"),
        _evidence(
            source="source-a",
            when=date(2014, 6, 1),
            name="Other Corporation",
            symbol="OTH",
        ),
        _evidence(
            source="source-b",
            when=date(2014, 6, 1),
            name="Shared Alias",
            symbol="OTH",
        ),
    )

    assert not derive_cross_source_issuer_aliases(evidence, sec_index=sec_index)
